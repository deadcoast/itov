"""Versioned, integer-declared media settings; no inferred quality/capacity promise."""

from itov.catalog import integer, object_fields, require


def sampler(value, kind):
    fields = {"steps", "cfg_milli"} | ({"shift_milli"} if kind == "video" else set())
    object_fields(value, fields, "media sampler")
    for key in fields:
        integer(value[key], key)
    require(10 <= value["steps"] <= (30 if kind == "video" else 100), "Unsupported sampler steps")
    require(1000 <= value["cfg_milli"] <= 10000, "CFG must be within 1000..10000 milli")
    if kind == "video":
        require(1000 <= value["shift_milli"] <= 16000, "Shift must be within 1000..16000 milli")
    return value


def video_contract(spec):
    return {
        **({"version": 2} if spec["version"] == 2 else {}),
        **{key: spec[key] for key in ("width", "height", "frames", "fps")},
    }


def extended_graph(graph):
    """Extended output contracts must describe the actual stock generation graph."""
    audio_limit = 10
    for node in graph.values():
        kind = node["class_type"]
        key = {"SaveVideo": "itov_video", "SaveAudioAdvanced": "itov_audio"}.get(kind)
        metadata = node.get("_meta", {})
        require(isinstance(metadata, dict), "Media metadata must be an object")
        contract = metadata.get(key) if key else None
        if not isinstance(contract, dict) or contract.get("version") != 2:
            continue

        def one(name):
            rows = [n["inputs"] for n in graph.values() if n["class_type"] == name]
            require(len(rows) == 1, f"Extended media requires exactly one {name}")
            return rows[0]

        def connected(inputs, field, name, output=0):
            identifiers = [key for key, item in graph.items() if item["class_type"] == name]
            require(
                len(identifiers) == 1 and inputs[field] == [identifiers[0], output],
                f"Extended media requires a direct {field} link to {name}",
            )

        settings = one("KSampler")
        require(type(settings["steps"]) is int, "Sampler steps must be an integer")
        require(type(settings["cfg"]) in (int, float), "Sampler CFG must be numeric")
        declared = {"steps": settings["steps"], "cfg_milli": round(settings["cfg"] * 1000)}
        require(declared["cfg_milli"] / 1000 == settings["cfg"], "CFG exceeds milli precision")
        if kind == "SaveVideo":
            from itov.media import video_contract as validate_video

            validate_video(contract)
            latent = one("Wan22ImageToVideoLatent")
            connected(node["inputs"], "video", "CreateVideo")
            connected(one("CreateVideo"), "images", "VAEDecode")
            connected(one("VAEDecode"), "samples", "KSampler")
            connected(settings, "latent_image", "Wan22ImageToVideoLatent")
            connected(settings, "model", "ModelSamplingSD3")
            connected(latent, "start_image", "LoadImage")
            require(
                all(latent[k] == contract[k] for k in ("width", "height"))
                and latent["length"] == contract["frames"]
                and one("CreateVideo")["fps"] == contract["fps"],
                "Extended video graph and output contract differ",
            )
            shift = one("ModelSamplingSD3")["shift"]
            require(type(shift) in (int, float), "Sampler shift must be numeric")
            declared["shift_milli"] = round(shift * 1000)
            require(declared["shift_milli"] / 1000 == shift, "Shift exceeds milli precision")
            sampler(declared, "video")
            expected_sampler = ("uni_pc", "simple")
        else:
            from itov.audio_media import audio_contract

            audio_contract(contract)
            seconds = one("EmptyLatentAudio")["seconds"]
            connected(node["inputs"], "audio", "VAEDecodeAudio")
            connected(one("VAEDecodeAudio"), "samples", "KSampler")
            connected(settings, "latent_image", "EmptyLatentAudio")
            connected(settings, "positive", "ConditioningStableAudio")
            connected(settings, "negative", "ConditioningStableAudio", 1)
            require(
                type(seconds) is int
                and 1 <= seconds <= 47
                and round(seconds * 44100 / 4096) * 4096 == contract["samples"]
                and one("ConditioningStableAudio")["seconds_total"] == seconds,
                "Extended audio graph and output contract differ",
            )
            sampler(declared, "audio")
            audio_limit = 47
            expected_sampler = ("dpmpp_3m_sde_gpu", "exponential")
        require(
            (settings["sampler_name"], settings["scheduler"]) == expected_sampler
            and settings["denoise"] == 1,
            "Extended media sampler contract differs",
        )
    return audio_limit
