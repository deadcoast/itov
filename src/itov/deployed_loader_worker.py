"""Optional CPU-only probe of the installed ComfyUI loader; invoked in its Python."""

import json
import os
import sys
from pathlib import Path


def tensor_pair(tensors, key_map, target, up, down):
    # ComfyUI adapters share one cumulative loaded_keys set. Trace the actual
    # tensor objects held by this patch instead of treating that set as per-patch.
    up_names = [name for name, tensor in tensors.items() if tensor is up]
    down_names = [name for name, tensor in tensors.items() if tensor is down]
    assert len(up_names) == len(down_names) == 1, "Ambiguous loaded tensor identity"
    up_name, down_name = up_names[0], down_names[0]
    assert up_name.endswith(".lora_up.weight")
    assert down_name == up_name.replace(".lora_up.", ".lora_down.")
    assert key_map[up_name.removesuffix(".lora_up.weight")] == target
    return sorted([up_name, down_name])


def probe(request):
    # Some optional ComfyUI imports probe CUDA even with --cpu. Hide devices
    # before importing them so this host-only inspection cannot acquire CUDA.
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    sys.path.insert(0, request["comfyui_root"])
    # ComfyUI parses these before choosing a device. All model tensors stay on CPU.
    sys.argv = [__file__, "--cpu", "--fp16-unet", "--disable-all-custom-nodes"]
    import comfy.options

    comfy.options.enable_args_parsing()
    import comfy.lora
    import comfy.lora_convert
    import comfy.sd
    import comfy.utils
    import torch

    model = comfy.sd.load_checkpoint_guess_config(
        request["checkpoint"], output_vae=False, output_clip=False
    )[0]
    assert model is not None, "ComfyUI did not load a checkpoint model"
    state = model.model.state_dict()
    assert all(t.device.type == "cpu" for t in state.values()), "Non-CPU checkpoint tensor"
    lora = comfy.utils.load_torch_file(request["adapter"], safe_load=True)
    converted = comfy.lora_convert.convert_lora(lora)
    assert set(lora) == set(converted), "Unexpected export conversion"
    key_map = comfy.lora.model_lora_keys_unet(model.model, {})
    loaded = comfy.lora.load_lora(converted, key_map)
    rows, consumed = [], set()
    for target, adapter in sorted(loaded.items()):
        assert adapter.name == "lora", "Unexpected patch type"
        up, down, alpha, mid, dora, reshape = adapter.weights
        keys = tensor_pair(converted, key_map, target, up, down)
        assert len(keys) == 2 and not consumed.intersection(keys), "Duplicate/extra tensors"
        consumed.update(keys)
        assert alpha is None and mid is None and dora is None and reshape is None
        assert tuple(state[target].shape) == (up.shape[0], down.shape[1])
        assert up.ndim == down.ndim == 2 and up.shape[1] == down.shape[0]
        assert torch.isfinite(up).all() and torch.isfinite(down).all()
        assert up.device.type == down.device.type == "cpu"
        rows.append(
            {
                "target": target,
                "tensors": keys,
                "base_shape": list(state[target].shape),
                "up_shape": list(up.shape),
                "down_shape": list(down.shape),
                "patch_type": adapter.name,
                "alpha_scale_milli": 1000,
            }
        )
    assert consumed == set(lora), "Unconsumed deployed tensors"
    accepted = []
    for strength in request["strengths_milli"]:
        patched, clip = comfy.sd.load_lora_for_models(model, None, lora, strength / 1000, 0)
        assert patched is not None, "ComfyUI did not return a patched model"
        assert clip is None and set(patched.patches) == set(loaded)
        assert all(
            len(p) == 1 and p[0][0] == strength / 1000 and p[0][2:] == (1.0, None, None)
            for p in patched.patches.values()
        )
        accepted.append({"strength_milli": strength, "targets": sorted(patched.patches)})
    assert torch.cuda.device_count() == 0, "Probe exposed a CUDA device"
    return {
        "version": 1,
        "device": "cpu",
        "cuda_initialized": torch.cuda.is_initialized(),
        "visible_cuda_devices": 0,
        "torch_version": str(torch.__version__),
        "model_class": type(model.model).__name__,
        "rows": rows,
        "accepted": accepted,
        "unconsumed": [],
    }


if __name__ == "__main__":
    request_path, output_path = map(Path, sys.argv[1:])
    result = probe(json.loads(request_path.read_bytes()))
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
