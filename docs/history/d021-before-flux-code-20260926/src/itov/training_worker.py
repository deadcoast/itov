"""Optional Diffusers/PEFT worker. Never imported by the dependency-light CLI."""

from __future__ import annotations

import gc
import os
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from itov.catalog import read_document, require, sha256
from itov.comfyui import parse_json
from itov.training_data import file_ref, load_dataset, publish, seal


def train(request):
    import numpy as np
    import torch
    from diffusers import DDPMScheduler, StableDiffusionXLPipeline
    from diffusers.utils import convert_state_dict_to_diffusers
    from peft import LoraConfig
    from peft.utils import get_peft_model_state_dict
    from PIL import Image

    from itov.training import probe, worker_sources

    value = request["plan"]
    spec, root, output = value["specification"], Path(request["workspace"]), Path(request["output"])
    require(worker_sources() == value["worker_sources"], "Worker source changed after planning")
    require(probe(Path(sys.executable)) == value["environment"], "Worker environment changed")
    dataset = load_dataset(root, root / spec["dataset"]["path"])
    require(dataset["dataset_id"] == value["dataset_id"], "Worker dataset differs")
    params = spec["parameters"]
    configured = spec["version"] in (3, 4)
    durable = spec["version"] == 4
    if configured:
        from itov import training_config

        require(
            value["optimization"] == training_config.resolve(spec, dataset["dataset"]["samples"]),
            "Worker optimization configuration differs",
        )
        publish(output / "optimization" / "effective.json", value["optimization"])
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    torch.manual_seed(params["seed"])
    if durable:
        import random

        random.seed(params["seed"])
        np.random.seed(params["seed"])
    require(
        torch.cuda.is_available() and torch.cuda.device_count() == 1,
        "One selected CUDA device is required",
    )
    require(torch.cuda.is_bf16_supported(), "Training device must support BF16")
    if configured:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    torch.cuda.reset_peak_memory_stats()
    print("Loading pinned local SDXL checkpoint", flush=True)
    pipe = StableDiffusionXLPipeline.from_single_file(
        request["checkpoint"],
        config=str(root / spec["model_config"]["directory"]),
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        use_safetensors=True,
        add_watermarker=False,
    )
    scheduler = DDPMScheduler.from_config(pipe.scheduler.config)
    require(
        scheduler.config.prediction_type == "epsilon", "Only SDXL epsilon prediction is supported"
    )
    for module in (pipe.unet, pipe.vae, pipe.text_encoder, pipe.text_encoder_2):
        module.requires_grad_(False)
        module.eval()
    cached = []
    print("Caching frozen caption embeddings", flush=True)
    # Encode captions separately from images so the VAE/text encoders never share VRAM.
    pipe.text_encoder.to("cuda")
    pipe.text_encoder_2.to("cuda")
    with torch.no_grad():
        for sample in sorted(dataset["dataset"]["samples"], key=lambda s: s["id"]):
            caption = (root / sample["caption"]["path"]).read_text(encoding="utf-8").strip()
            embeds, _, pooled, _ = pipe.encode_prompt(
                prompt=caption, device=torch.device("cuda"), do_classifier_free_guidance=False
            )
            cached.append(
                {
                    "id": sample["id"],
                    "split": sample["split"],
                    "sample": sample,
                    "embeds": embeds.cpu(),
                    "pooled": pooled.cpu(),
                }
            )
    pipe.text_encoder.to("cpu")
    pipe.text_encoder_2.to("cpu")
    gc.collect()
    torch.cuda.empty_cache()
    pipe.vae.to(device="cuda", dtype=torch.float32)
    print("Caching frozen image latents", flush=True)
    with torch.no_grad():
        for item in cached:
            image_path = root / item["sample"]["image"]["path"]
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                require(
                    image.mode == "RGB" and image.size == (512, 512),
                    "Decoded image differs from prepared RGB contract",
                )
                pixels = np.asarray(image, dtype=np.float32).copy() / 127.5 - 1
            tensor = torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0).to("cuda")
            latent = pipe.vae.encode(tensor).latent_dist.mode() * pipe.vae.config.scaling_factor
            require(bool(torch.isfinite(latent).all()), "Nonfinite VAE latent")
            item["latent"] = latent.cpu().to(torch.bfloat16)
    pipe.vae.to("cpu")
    # The encoders are frozen, and their cached values never receive gradients.
    gc.collect()
    torch.cuda.empty_cache()
    unet = pipe.unet
    unet.add_adapter(
        LoraConfig(
            r=params["rank"],
            lora_alpha=params["rank"],
            init_lora_weights="gaussian",
            target_modules=["to_q", "to_k", "to_v", "to_out.0"],
        )
    )
    learned = [parameter for parameter in unet.parameters() if parameter.requires_grad]
    require(bool(learned), "No trainable LoRA parameters")
    for parameter in learned:
        parameter.data = parameter.data.float()
    require(
        all("lora_" in name for name, p in unet.named_parameters() if p.requires_grad),
        "Non-adapter parameters are trainable",
    )
    initial = {
        name: tensor.detach().cpu().clone()
        for name, tensor in get_peft_model_state_dict(unet).items()
    }
    unet.to("cuda")
    time_ids = torch.tensor([[512, 512, 0, 0, 512, 512]], device="cuda", dtype=torch.bfloat16)

    def loss(item, seed):
        generator = torch.Generator(device="cuda").manual_seed(seed)
        latent = item["latent"].to("cuda")
        noise = torch.randn(latent.shape, device="cuda", dtype=latent.dtype, generator=generator)
        timestep = torch.randint(
            0, scheduler.config.num_train_timesteps, (1,), device="cuda", generator=generator
        )
        noisy = scheduler.add_noise(latent, noise, timestep)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            prediction = unet(
                noisy,
                timestep,
                encoder_hidden_states=item["embeds"].to("cuda"),
                added_cond_kwargs={"text_embeds": item["pooled"].to("cuda"), "time_ids": time_ids},
            ).sample
        value = torch.nn.functional.mse_loss(prediction.float(), noise.float())
        require(bool(torch.isfinite(value)), "Nonfinite denoising loss")
        return value

    heldout = [item for item in cached if item["split"] == "validation"]
    training = [item for item in cached if item["split"] == "train"]

    def evaluate():
        unet.eval()
        with torch.no_grad():
            return [
                {
                    "sample": item["id"],
                    "noise_seed": (params["seed"] + 100000 + index) % 2**32,
                    "loss_billionths": round(
                        float(loss(item, (params["seed"] + 100000 + index) % 2**32)) * 10**9
                    ),
                }
                for index, item in enumerate(heldout)
            ]

    print("Evaluating held-out losses before optimization", flush=True)
    unet.enable_gradient_checkpointing()
    optimization_ref = None
    checkpoint_manager = None
    if configured:
        from itov.training_optimization import optimize
        from itov.windows_process import host_memory

        training_by_id = {item["id"]: item for item in training}
        frozen = [p for p in unet.parameters() if not p.requires_grad]
        require(all(p.dtype == torch.bfloat16 for p in frozen), "Frozen UNet precision differs")
        require(
            all(p.dtype == torch.float32 for p in learned), "Trainable adapter precision differs"
        )
        require(next(pipe.vae.parameters()).dtype == torch.float32, "VAE precision differs")
        precision = {
            "frozen_unet_dtype": str(frozen[0].dtype),
            "adapter_dtype": str(learned[0].dtype),
            "gradient_dtype": "torch.float32",
            "vae_dtype": str(next(pipe.vae.parameters()).dtype),
            "autocast_dtype": "torch.bfloat16",
            "loss_dtype": "torch.float32",
            "tf32": False,
            "adapter_tensors": len(learned),
        }
        publish(output / "optimization" / "precision.json", precision)

        def batch_loss(rows):
            latents, noises, timesteps, embeds, pooled = [], [], [], [], []
            for row in rows:
                item = training_by_id[row["sample"]]
                generator = torch.Generator(device="cuda").manual_seed(row["noise_seed"])
                latent = item["latent"].to("cuda")
                latents.append(latent)
                noises.append(
                    torch.randn(
                        latent.shape, device="cuda", dtype=latent.dtype, generator=generator
                    )
                )
                timesteps.append(
                    torch.randint(
                        0,
                        scheduler.config.num_train_timesteps,
                        (1,),
                        device="cuda",
                        generator=generator,
                    )
                )
                embeds.append(item["embeds"].to("cuda"))
                pooled.append(item["pooled"].to("cuda"))
            latent, noise, timestep = torch.cat(latents), torch.cat(noises), torch.cat(timesteps)
            noisy = scheduler.add_noise(latent, noise, timestep)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                prediction = unet(
                    noisy,
                    timestep,
                    encoder_hidden_states=torch.cat(embeds),
                    added_cond_kwargs={
                        "text_embeds": torch.cat(pooled),
                        "time_ids": time_ids.repeat(len(rows), 1),
                    },
                ).sample
            require(prediction.dtype == torch.bfloat16, "UNet autocast output precision differs")
            return (
                torch.nn.functional.mse_loss(prediction.float(), noise.float(), reduction="none")
                .flatten(1)
                .mean(1)
                .mean()
            )

        def observe():
            host = host_memory()
            previous_allocated = checkpoint_manager.peak_allocated if checkpoint_manager else 0
            previous_reserved = checkpoint_manager.peak_reserved if checkpoint_manager else 0
            return {
                "cuda_allocated_bytes": torch.cuda.memory_allocated(),
                "cuda_reserved_bytes": torch.cuda.memory_reserved(),
                "cuda_peak_allocated_bytes": max(
                    torch.cuda.max_memory_allocated(), previous_allocated
                ),
                "cuda_peak_reserved_bytes": max(
                    torch.cuda.max_memory_reserved(), previous_reserved
                ),
                "host_available_physical_bytes": host["available_physical"],
                "host_available_commit_bytes": host["available_commit"],
            }

        def emit(kind, step, row):
            publish(output / "optimization" / f"{kind}-{step:06d}.json", row)

        if durable:
            from types import SimpleNamespace

            from itov import training_checkpoints
            from itov.training_checkpoint_worker import Checkpoints, runtime
            from itov.vram import gpu_snapshot

            source = (
                training_checkpoints.restart(SimpleNamespace(root=root), value)
                if value["restart"]
                else None
            )
            checkpoint_manager = Checkpoints(
                value, output, unet, precision, runtime(gpu_snapshot()), emit, source
            )
        steps, validation = optimize(
            unet,
            learned,
            value["optimization"],
            batch_loss,
            evaluate,
            observe,
            emit,
            torch.cuda.synchronize,
            restore=checkpoint_manager.restore if checkpoint_manager else None,
            checkpoint=checkpoint_manager.save if checkpoint_manager else None,
        )
        losses = [row["loss_billionths"] for row in steps]
        before, after = validation[0]["losses"], validation[-1]["losses"]
        trace = {
            "version": 1,
            "plan_id": value["plan_id"],
            "config": value["optimization"]["config"],
            "precision": precision,
            "steps": steps,
            "validation": validation,
        }
        trace_path = publish(output / "optimization.json", trace)
        optimization_ref = {"path": "optimization.json", "sha256": sha256(trace_path.read_bytes())}
    else:
        before = evaluate()
        unet.train()
        optimizer = torch.optim.AdamW(learned, lr=params["learning_rate_millionths"] / 10**6)
        losses = []
        for step in range(params["steps"]):
            optimizer.zero_grad(set_to_none=True)
            value_loss = loss(training[step % len(training)], (params["seed"] + step) % 2**32)
            value_loss.backward()
            require(
                all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in learned),
                "Nonfinite LoRA gradient",
            )
            norm = torch.nn.utils.clip_grad_norm_(learned, 1.0)
            require(bool(torch.isfinite(norm)), "Nonfinite gradient norm")
            optimizer.step()
            losses.append(round(float(value_loss.detach()) * 10**9))
            print(
                f"Optimizer step {step + 1}/{params['steps']}: loss_billionths={losses[-1]}",
                flush=True,
            )
        after = evaluate()
        optimizer.zero_grad(set_to_none=True)
        del optimizer
    state = {
        name: tensor.detach().float().cpu().contiguous()
        for name, tensor in get_peft_model_state_dict(unet).items()
    }
    require(
        all(bool(torch.isfinite(tensor).all()) for tensor in state.values()),
        "Nonfinite saved LoRA values",
    )
    changed = sum(not torch.equal(tensor, initial[name]) for name, tensor in state.items())
    require(changed > 0, "Training did not change any adapter tensors")
    StableDiffusionXLPipeline.save_lora_weights(
        str(output),
        unet_lora_layers=convert_state_dict_to_diffusers(state),
        safe_serialization=True,
    )
    weights = output / "pytorch_lora_weights.safetensors"
    weights_ref = {"path": weights.name, "sha256": sha256(weights.read_bytes())}
    file_ref(output, weights_ref)
    # Exercise the serialized export, not just the live adapter used by the optimizer.
    pipe.unload_lora_weights()
    pipe.load_lora_weights(str(output), weight_name=weights.name, local_files_only=True)
    print("Reloaded exported LoRA for paired previews", flush=True)
    # Paired held-out inference uses the same seeds/prompts with adapters disabled/enabled.
    # Images are review artifacts; their existence is not a passing quality verdict.
    unet.disable_gradient_checkpointing()
    pipe.to("cuda")
    pipe.set_progress_bar_config(disable=True)
    previews = []

    def render(prompt, negative_prompt, seed, enabled, path):
        if enabled:
            unet.enable_adapters()
        else:
            unet.disable_adapters()
        latents = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=512,
            height=512,
            num_inference_steps=20,
            guidance_scale=7.0,
            generator=torch.Generator(device="cuda").manual_seed(seed),
            output_type="latent",
        ).images
        require(
            getattr(pipe.vae.config, "latents_mean", None) is None
            and getattr(pipe.vae.config, "latents_std", None) is None,
            "Only the pinned SDXL VAE scaling contract is supported",
        )
        with torch.no_grad():
            decoded = pipe.vae.decode(
                latents.to(dtype=torch.float32) / pipe.vae.config.scaling_factor,
                return_dict=False,
            )[0]
        require(bool(torch.isfinite(decoded).all()), "Nonfinite preview pixels")
        pipe.image_processor.postprocess(decoded, output_type="pil")[0].save(path)
        return {"path": path.name, "sha256": sha256(path.read_bytes())}

    for index, item in enumerate(heldout[:2]):
        caption = (root / item["sample"]["caption"]["path"]).read_text(encoding="utf-8").strip()
        seed = (params["seed"] + 200000 + index) % 2**32
        pair = {"sample": item["id"], "seed": seed, "prompt": caption}
        for label, enabled in (("baseline", False), ("candidate", True)):
            path = output / f"{item['id']}-{label}.png"
            pair[label] = render(caption, "", seed, enabled, path)
            print(f"Saved held-out {label}: {path.name}", flush=True)
        previews.append(pair)
    matrix = []
    if spec["version"] in (2, 3, 4):
        from itov.quality import expected, qualification

        _, suite = qualification(root, spec)
        for row in expected(suite):
            path = output / f"quality-{row['case_id']}-{row['seed']}-{row['role']}.png"
            ref = render(
                row["prompt"],
                row["negative_prompt"],
                row["seed"],
                row["role"].startswith("adapter"),
                path,
            )
            matrix.append({**row, "image": ref})
            print(f"Saved quality comparison: {path.name}", flush=True)
    # Repeat all dataset reads after training; concurrent source edits invalidate the receipt.
    require(
        load_dataset(root, root / spec["dataset"]["path"])["dataset_id"] == value["dataset_id"],
        "Dataset changed during training",
    )
    return {
        "version": spec["version"],
        "plan_id": value["plan_id"],
        "status": "succeeded",
        "weights": weights_ref,
        "optimizer_steps": len(losses),
        "training_loss_billionths": losses,
        "heldout_before": before,
        "heldout_after": after,
        "previews": previews,
        **({"quality_matrix": matrix} if spec["version"] in (2, 3, 4) else {}),
        **({"optimization": optimization_ref} if configured else {}),
        **({"checkpoints": checkpoint_manager.references} if checkpoint_manager else {}),
        "changed_adapter_tensors": changed,
        "trainable_parameters": sum(p.numel() for p in learned),
        "adapter_only": True,
        "export_reloaded": True,
        "max_memory_allocated": max(
            torch.cuda.max_memory_allocated(),
            checkpoint_manager.peak_allocated if checkpoint_manager else 0,
        ),
        "max_memory_reserved": max(
            torch.cuda.max_memory_reserved(),
            checkpoint_manager.peak_reserved if checkpoint_manager else 0,
        ),
        "quality_acceptance": "not_established",
        "purpose": value["purpose"],
        "limits": (
            "Paired held-out denoising losses and previews are diagnostics, not activation, "
            "perceptual quality or promotion acceptance. No assertion of bitwise "
            "cross-runtime reproducibility."
        ),
    }


def main():
    request = parse_json(read_document(Path(sys.argv[1])))
    output = Path(request["output"])
    os.environ.update(
        CUDA_VISIBLE_DEVICES=request["gpu_uuid"],
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false",
        HF_HOME=str(output / "hf-cache"),
    )
    started = time.monotonic_ns()
    with (
        (output / "worker.log").open("x", encoding="utf-8", buffering=1) as log,
        redirect_stdout(log),
        redirect_stderr(log),
    ):
        try:
            result = train(request)
        except BaseException as error:
            traceback.print_exc()
            result = {
                "version": 1,
                "plan_id": request["plan"]["plan_id"],
                "status": "failed",
                "error": type(error).__name__ + ": " + str(error),
            }
        result["elapsed_ns"] = time.monotonic_ns() - started
        publish(output / "result.json", seal(result, "result_id"))
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
