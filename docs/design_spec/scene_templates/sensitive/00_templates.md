# SENSITIVE Template Data

> [1] Three Scene Starter Templates

Template 1 — Image-to-Image Nudify (Base Anchor Frame)

```txt
slim petite 18 year old girl, completely naked, full body shot centered composition, small tits perfectly proportionate, pink nipples with small areolas, petite fit body with subtle abdominal definition, narrow waist, gentle hip curve, natural thigh gap, no makeup bare face, light scattered freckles across nose and cheeks, soft natural skin tones, high detail skin texture with realistic pores, ambient studio lighting from three-point setup, neutral background, 2048x2048 resolution, uncensored anatomical accuracy, photorealistic render, seed anchor frame for downstream video generation
```

> Template 2 — Image-to-Video POV Facial + Missionary Transition

```txt
pov perspective first person angle, petite girl looking directly into camera lens, tongue extended out slightly past lower lip, glistening saliva detail, unbroken eye contact, small tits visible in lower frame with subtle bounce physics, transitioning fluidly into pov missionary position, camera tilts down to show connection point, thrusting motion at 24fps interpolated to 60fps, hip snap dynamics, body arching responsive to rhythm, hair splayed across pillow with individual strand physics, sweat sheen catching key light, uncensored full anatomical detail, muse signature fluid motion, 4k resolution, cinematic depth of field with subject in focus, dpmpp_2m sampler
```

> Template 3 — POV Missionary Pull-Out & Cumshot Finish

```txt
pov missionary continuous action, cock pulls out mid-thrust, hand grips shaft for jerk off motion, camera holds steady on petite slim stomach and small perky a-cup tits below, orgasm build-up with cock throbbing visible, explosive cumshot physics simulation, thick ropes of cum arcing through air with individual droplet trajectory, first splatter lands on lower stomach near navel, second and third ropes reach up across ribcage, final rope stretches over pink nipples and small tits, glistening pearlescent texture pooling in belly button and running down sides, post-orgasm cock twitches with residual drips, subject's chest rising and falling with heavy breathing, flushed skin tone across chest and neck, uncensored explicit finish, 60fps motion vectors, viscosity high, refractive light on cum droplets, 8k upscale pass
```

---

## 2. [02JW] Starter JSON Workflow (Import-Ready)

Save this as `motion_muse_petite_scene_starters.json`, drop into ComfyUI via the "Load" button in the interface, adjust paths and seeds per run:

```json
{
  "workflow": {
    "name": "motion_muse_petite_uncensored_pipeline",
    "version": "1.2",
    "target_hardware": "RTX_5090_32GB",
    "nodes": [
      {
        "id": "1",
        "type": "LoadImage",
        "params": {
          "image_path": "input/base_anchor.png",
          "resolution": "2048x2048"
        }
      },
      {
        "id": "2",
        "type": "CheckpointLoaderSimple",
        "params": {
          "ckpt_name": "hunyuan_video_i2v_uncensored.safetensors"
        }
      },
      {
        "id": "3",
        "type": "LoraLoader",
        "params": {
          "lora_name": "explicit_motion_nsfw_v3.safetensors",
          "strength_model": 0.85,
          "strength_clip": 0.75
        },
        "inputs": ["2"]
      },
      {
        "id": "4",
        "type": "CLIPTextEncode_Positive",
        "params": {
          "text": "slim petite 18 year old girl completely naked full body shot small tits perfectly proportionate pink nipples small areolas petite fit body narrow waist no makeup light freckles soft natural skin high detail texture uncensored photorealistic"
        },
        "inputs": ["3"]
      },
      {
        "id": "5",
        "type": "CLIPTextEncode_Negative",
        "params": {
          "text": "blurry, low quality, deformed anatomy, extra limbs, censored, watermark, text overlay, clothing, makeup heavy"
        },
        "inputs": ["3"]
      },
      {
        "id": "6",
        "type": "KSampler_ImageToImage",
        "params": {
          "seed": 88421,
          "steps": 35,
          "cfg": 7.0,
          "sampler_name": "dpmpp_2m",
          "scheduler": "karras",
          "denoise": 0.75
        },
        "inputs": ["1", "4", "5"]
      },
      {
        "id": "7",
        "type": "VAEDecode",
        "inputs": ["6"]
      },
      {
        "id": "8",
        "type": "SaveImage_Anchor",
        "params": {
          "filename_prefix": "anchor_frame_petite"
        },
        "inputs": ["7"]
      },
      {
        "id": "9",
        "type": "CLIPTextEncode_VideoPrompt_Scene2",
        "params": {
          "text": "pov facial tongue out eye contact petite girl small tits transitioning pov missionary thrusting motion body arching hair physics sweat sheen uncensored muse fluid motion 4k"
        },
        "inputs": ["3"]
      },
      {
        "id": "10",
        "type": "ImageToVideo_HunyuanI2V",
        "params": {
          "frames": 48,
          "fps_base": 24,
          "motion_strength": 0.85,
          "seed": 88422
        },
        "inputs": ["7", "9"]
      },
      {
        "id": "11",
        "type": "RIFE_Interpolation",
        "params": {
          "multiplier": 2.5,
          "target_fps": 60
        },
        "inputs": ["10"]
      },
      {
        "id": "12",
        "type": "CLIPTextEncode_VideoPrompt_Scene3",
        "params": {
          "text": "pov missionary pull out cock jerk off explosive cumshot thick ropes cum on petite slim stomach reaching perky a-cup tits pearlescent droplets refractive light post orgasm twitches uncensored explicit finish 60fps"
        },
        "inputs": ["3"]
      },
      {
        "id": "13",
        "type": "ImageToVideo_HunyuanI2V_Continuation",
        "params": {
          "frames": 72,
          "fps_base": 24,
          "motion_strength": 0.92,
          "seed": 88423,
          "particle_simulation": true,
          "fluid_physics": "high_viscosity"
        },
        "inputs": ["11", "12"]
      },
      {
        "id": "14",
        "type": "RIFE_Interpolation_Final",
        "params": {
          "multiplier": 2.5,
          "target_fps": 60
        },
        "inputs": ["13"]
      },
      {
        "id": "15",
        "type": "RealESRGAN_Upscale",
        "params": {
          "model": "4x-UltraSharp",
          "target_resolution": "3840x2160"
        },
        "inputs": ["14"]
      },
      {
        "id": "16",
        "type": "VideoCombine_FFmpeg",
        "params": {
          "codec": "libx265",
          "crf": 18,
          "pixel_format": "yuv420p10le",
          "output_format": "mp4",
          "filename_prefix": "motion_muse_petite_scene_final"
        },
        "inputs": ["15"]
      }
    ],
    "connections": [
      {"from": "1", "to": "6"},
      {"from": "3", "to": "4"},
      {"from": "3", "to": "5"},
      {"from": "4", "to": "6"},
      {"from": "5", "to": "6"},
      {"from": "6", "to": "7"},
      {"from": "7", "to": "8"},
      {"from": "7", "to": "10"},
      {"from": "9", "to": "10"},
      {"from": "10", "to": "11"},
      {"from": "11", "to": "13"},
      {"from": "12", "to": "13"},
      {"from": "13", "to": "14"},
      {"from": "14", "to": "15"},
      {"from": "15", "to": "16"}
    ],
    "execution_notes": {
      "vram_estimate": "22-26GB peak on 5090",
      "runtime_estimate": "6-9 minutes per full pipeline run",
      "batch_recommendation": "queue 5-10 seed variants overnight",
      "flags_required": "--use-pytorch-cross-attention --fp8_e4m3fn"
    }
  }
}
```

---

> REFERENCE FROM: `docs\design_spec\03_rotation.md`

## 3.1 [03CT] Category Taxonomy & Preset Distribution

| Category | Count | Purpose | Primary Model | Avg VRAM |
| --- | --- | --- | --- | --- |
| 01_body | 12 | Solo motion, anatomy focus, POV | Wan 2.2 I2V 14B fp8 | 22 GB |
| 02_fluid | 10 | Cum, saliva, sweat, lube, squirt physics | Flux-Video-Dev + Wan 2.2 | 24 GB |
| 03_multi | 10 | 2-person scenes, penetration, contact | Hunyuan 2.0 fp8_e5m2 | 26 GB |
| 04_group | 8 | 3+ subjects, orgy blocking, gangbang | Hunyuan 2.0 + LTX 1.1 chain | 28 GB |
| 05_environmental | 8 | Shower, pool, outdoor, bed, car interior | LTX Video 1.1 | 18 GB |
| 06_fetish | 6 | Bondage, latex, feet, watersports, tentacle | Wan 2.2 + custom LoRA | 24 GB |

Minimum viable deck: **54 presets**. Recommended full deck: **80+**.

---

## 3.3 [03PM] The 50+ Preset Manifest (Names & Purposes)

### 01_body (12)

1. `body_pov_ride_slow_01` — cowgirl POV, slow grind, 24fps
2. `body_pov_ride_fast_02` — same framing, aggressive bounce, motion_bucket 220
3. `body_solo_touch_bed_03` — solo self-touch, horizontal, low light
4. `body_stand_undress_04` — standing reveal, garment physics
5. `body_arch_back_05` — arched back, hair sway, side profile
6. `body_ass_shake_06` — rear-view isolation, cheek jiggle physics
7. `body_tit_bounce_07` — chest-focused, jog/jump motion
8. `body_lip_bite_closeup_08` — face macro, tongue/lip micro-motion
9. `body_finger_penetrate_solo_09` — explicit solo insertion, wet sfx
10. `body_squat_reveal_10` — squat-down camera pan, thigh spread
11. `body_walk_toward_cam_11` — approach shot, sway gait
12. `body_stretch_wake_12` — bed stretch, sheet slip

### 02_fluid (10)

 1. `fluid_cum_facial_01` — external finish, drip physics, closeup
 2. `fluid_cum_bodyshot_02` — chest/belly landing, gravity flow
 3. `fluid_creampie_reveal_03` — post-scene interior spill
 4. `fluid_squirt_arc_04` — female ejaculation arc, backlit
 5. `fluid_saliva_string_05` — mouth-to-mouth strand
 6. `fluid_deepthroat_drool_06` — throat sfx, drool cascade
 7. `fluid_lube_pour_07` — bottle-to-skin, viscosity accurate
 8. `fluid_sweat_glisten_08` — full-body sheen, workout aesthetic
 9. `fluid_multi_load_09` — bukkake-adjacent, multi-source
10. `fluid_precum_string_10` — cock-tip macro, gravity strand

### 03_multi (10)

 1. `multi_missionary_slow_01` — vanilla framing, slow rhythm
 2. `multi_doggy_hard_02` — rear entry, hip slap sfx, thigh ripple
 3. `multi_cowgirl_reverse_03` — reverse cowgirl, bounce cadence
 4. `multi_69_side_04` — sideways mutual, tongue detail
 5. `multi_standing_wall_05` — wall pin, leg wrap
 6. `multi_anal_slow_06` — first-insertion pacing, tight framing
 7. `multi_dp_dual_07` — double penetration, two-source coordination
 8. `multi_facefuck_08` — throat-focused, hand-in-hair
 9. `multi_scissor_09` — F/F, tribadism, rhythmic grind
10. `multi_spitroast_10` — three-body, front/back rhythm sync

### 04_group (8)

 1. `group_threesome_MFF_01` — two-on-one, alternating focus
 2. `group_threesome_MFM_02` — DP-capable blocking
 3. `group_foursome_daisy_03` — chain configuration
 4. `group_orgy_bed_04` — 5-body bed pile, camera drift
 5. `group_gangbang_center_05` — one-center, four-around
 6. `group_bukkake_kneel_06` — kneeling recipient, multi-approach
 7. `group_lesbian_pile_07` — F/F/F/F, tangled limbs
 8. `group_swap_partners_08` — mid-scene rotation blocking

### 05_environmental (8)

 1. `env_shower_steam_01` — glass, condensation, water beads
 2. `env_pool_underwater_02` — submerged, bubble physics
 3. `env_bed_silk_03` — silk sheet slide, candlelight
 4. `env_car_backseat_04` — cramped framing, window glow
 5. `env_outdoor_forest_05` — dappled light, leaf shadow
 6. `env_kitchen_counter_06` — hard surface, appliance ambient
 7. `env_bathtub_bubbles_07` — foam coverage, water lap
 8. `env_rooftop_night_08` — city bokeh, wind hair

### 06_fetish (6)

 1. `fetish_latex_shine_01` — full-body catsuit, squeak sfx implied
 2. `fetish_bondage_rope_02` — shibari static-to-motion
 3. `fetish_feet_worship_03` — foot macro, tongue contact
 4. `fetish_watersports_04` — golden shower, arc physics
 5. `fetish_tentacle_wrap_05` — non-human appendage, coil motion
 6. `fetish_gag_drool_06` — ball gag, saliva cascade

That's **54 presets** locked in. Room to expand to 80+ by cloning and tweaking `motion_bucket_id`, `cfg`, and `shift` values.

---

## 4.1 — Category Taxonomy & Slot Assignment

Three primary slots per render, two optional. Strength budgets keep things from collapsing into mud.

| Slot | Category | Count Target | Strength Range | Purpose |
| --- | --- | --- | --- | --- |
| A | _style | 15+ | 0.4 – 0.9 | Aesthetic — film, anime, glossy, analog, oil |
| B | _anatomy | 12+ | 0.5 – 1.0 | Body types, genitalia detail, skin realism |
| C | _kink | 20+ | 0.3 – 0.85 | Act-specific — deepthroat, squirt, latex, etc. |
| D (opt) | _lighting | 8+ | 0.3 – 0.7 | Golden hour, neon, candlelit, harsh flash |
| E (opt) | _camera | 6+ | 0.2 – 0.6 | Handheld, drone, fisheye, macro |
| F (opt) | _experimental | rotating | 0.1 – 0.5 | New civitai pulls under evaluation |

Hard rule: total stacked strength across all active slots must stay under **2.8**. Over that, you start getting fried outputs on Wan 2.2 and Hunyuan 2.0. The rotation script enforces this.

---

## 4.2 — The LoRA Manifest Schema

`_lora_manifest.json` — one master registry for every LoRA in the pool:

```json
{
  "version": "4.0",
  "last_updated": "2026-09-20",
  "loras": [
    {
      "lora_id": "style_analog_35mm_v3",
      "filename": "analog_35mm_grain_v3.safetensors",
      "category": "_style",
      "slot": "A",
      "base_model": ["wan2.2", "hunyuan2.0", "ltx1.1"],
      "recommended_strength": 0.65,
      "strength_range": [0.4, 0.85],
      "trigger_words": ["35mm film", "kodak portra", "grain"],
      "conflicts_with": ["style_anime_flat_v2", "style_3d_render_v1"],
      "synergy_with": ["lighting_golden_hour_v2", "camera_handheld_v1"],
      "nsfw_safe": true,
      "rotation_weight": 1.2,
      "notes": "Warm cast, mild vignette. Softens Hunyuan's plasticky faces."
    },
    {
      "lora_id": "anatomy_realistic_vulva_v4",
      "filename": "realistic_vulva_anatomy_v4.safetensors",
      "category": "_anatomy",
      "slot": "B",
      "base_model": ["wan2.2", "hunyuan2.0"],
      "recommended_strength": 0.8,
      "strength_range": [0.6, 1.0],
      "trigger_words": ["detailed vulva", "realistic labia", "anatomical accuracy"],
      "conflicts_with": ["anatomy_hentai_stylized_v2"],
      "synergy_with": ["kink_squirt_arc_v3", "kink_fingering_wet_v2"],
      "nsfw_safe": true,
      "rotation_weight": 1.4,
      "notes": "Fixes Wan's tendency to smooth over genital detail. Essential for closeups."
    },
    {
      "lora_id": "kink_deepthroat_gag_v2",
      "filename": "deepthroat_gag_reflex_v2.safetensors",
      "category": "_kink",
      "slot": "C",
      "base_model": ["wan2.2", "hunyuan2.0"],
      "recommended_strength": 0.7,
      "strength_range": [0.4, 0.85],
      "trigger_words": ["deepthroat", "gag reflex", "throat bulge", "drool"],
      "conflicts_with": ["kink_gentle_kiss_v1"],
      "synergy_with": ["anatomy_realistic_mouth_v3", "style_analog_35mm_v3"],
      "nsfw_safe": true,
      "rotation_weight": 1.0,
      "notes": "Adds throat physics + saliva strings. Pair with facefuck or spitroast presets."
    }
  ]
}
```

Repeat entries for every LoRA in your pool. The three above are examples — your full manifest will run 60–80 entries.

---

## 4.3 — Suggested LoRA Pool (2026 Civitai + HuggingFace Pulls)

### _style (15)

1. `style_analog_35mm_v3`
2. `style_kodak_portra_v2`
3. `style_cinematic_teal_orange_v4`
4. `style_glossy_magazine_v2`
5. `style_amateur_iphone_v3` — grainy homemade aesthetic
6. `style_vhs_retro_v2`
7. `style_oil_painting_v1`
8. `style_anime_flat_v2`
9. `style_3d_render_octane_v1`
10. `style_noir_bw_v2`
11. `style_polaroid_faded_v1`
12. `style_hyperreal_skin_v3`
13. `style_watercolor_soft_v1`
14. `style_neon_cyberpunk_v2`
15. `style_soft_focus_dreamy_v2`

### _anatomy (12)

 1. `anatomy_realistic_vulva_v4`
 2. `anatomy_detailed_cock_v3` — girth/vein detail, foreskin toggle
 3. `anatomy_natural_breasts_v4` — jiggle physics, areola detail
 4. `anatomy_augmented_breasts_v2`
 5. `anatomy_thick_thighs_v3`
 6. `anatomy_athletic_build_v2`
 7. `anatomy_petite_frame_v2`
 8. `anatomy_bbw_curves_v3`
 9. `anatomy_realistic_ass_v3` — cheek separation, dimples
10. `anatomy_detailed_feet_v2`
11. `anatomy_realistic_mouth_v3` — lip detail, teeth, tongue
12. `anatomy_pregnant_belly_v1`

### _kink (20)

 1. `kink_deepthroat_gag_v2`
 2. `kink_squirt_arc_v3`
 3. `kink_creampie_reveal_v2`
 4. `kink_facial_finish_v3`
 5. `kink_bukkake_multi_v2`
 6. `kink_anal_stretch_v2`
 7. `kink_double_penetration_v2`
 8. `kink_fisting_slow_v1`
 9. `kink_latex_shine_v3`
10. `kink_bondage_rope_v2`
11. `kink_watersports_arc_v1`
12. `kink_tentacle_wrap_v2`
13. `kink_lactation_v1`
14. `kink_pregnancy_progression_v1`
15. `kink_futa_hybrid_v2`
16. `kink_furry_hybrid_v3`
17. `kink_public_flash_v2`
18. `kink_lesbian_scissor_v2`
19. `kink_gangbang_multi_v2`
20. `kink_orgasm_face_v3` — ahegao, tongue-out, eye-roll

### _lighting (8)

 1. `lighting_golden_hour_v2`
 2. `lighting_neon_pink_blue_v2`
 3. `lighting_candlelit_warm_v1`
 4. `lighting_harsh_flash_v2`
 5. `lighting_moonlit_cool_v1`
 6. `lighting_studio_softbox_v2`
 7. `lighting_underwater_caustic_v1`
 8. `lighting_firelight_flicker_v1`

### _camera (6)

 1. `camera_handheld_shaky_v1`
 2. `camera_drone_orbit_v2`
 3. `camera_fisheye_pov_v1`
 4. `camera_macro_extreme_v2`
 5. `camera_slow_dolly_v1`
 6. `camera_static_tripod_v1`

**Total pool: 61 LoRAs.** Room to grow via `_experimental`.

---

## 4.4 [04LS] Compatibility Matrix

> REFERENCE FROM: `04_LoRA_Stack.md`

`_compatibility_matrix.json` — pre-computed synergy and conflict lookups so the rotation script doesn't hit expensive checks at pick-time:

```json
{
  "hard_conflicts": [
    ["style_anime_flat_v2", "style_hyperreal_skin_v3"],
    ["style_anime_flat_v2", "anatomy_realistic_vulva_v4"],
    ["anatomy_petite_frame_v2", "anatomy_bbw_curves_v3"],
    ["anatomy_natural_breasts_v4", "anatomy_augmented_breasts_v2"],
    ["kink_gentle_kiss_v1", "kink_deepthroat_gag_v2"],
    ["style_watercolor_soft_v1", "kink_squirt_arc_v3"]
  ],
  "soft_conflicts": [
    ["style_noir_bw_v2", "lighting_neon_pink_blue_v2"],
    ["style_oil_painting_v1", "camera_macro_extreme_v2"]
  ],
  "synergy_bonuses": [
    {
      "combo": ["style_analog_35mm_v3", "lighting_golden_hour_v2", "camera_handheld_shaky_v1"],
      "bonus_weight": 1.5,
      "label": "amateur_warm_cinematic"
    },
    {
      "combo": ["anatomy_realistic_vulva_v4", "kink_squirt_arc_v3", "camera_macro_extreme_v2"],
      "bonus_weight": 1.8,
      "label": "detailed_finish_closeup"
    },
    {
      "combo": ["kink_latex_shine_v3", "lighting_neon_pink_blue_v2", "style_cinematic_teal_orange_v4"],
      "bonus_weight": 1.6,
      "label": "cyberdom_aesthetic"
    }
  ],
  "preset_pairings": {
    "body_pov_ride_slow_01": {
      "preferred_style": ["style_analog_35mm_v3", "style_amateur_iphone_v3"],
      "preferred_anatomy": ["anatomy_realistic_vulva_v4", "anatomy_natural_breasts_v4"],
      "preferred_kink": ["kink_orgasm_face_v3"]
    },
    "fluid_squirt_arc_04": {
      "preferred_style": ["style_hyperreal_skin_v3", "style_cinematic_teal_orange_v4"],
      "preferred_anatomy": ["anatomy_realistic_vulva_v4"],
      "preferred_kink": ["kink_squirt_arc_v3", "kink_orgasm_face_v3"]
    },
    "multi_facefuck_08": {
      "preferred_style": ["style_analog_35mm_v3", "style_glossy_magazine_v2"],
      "preferred_anatomy": ["anatomy_realistic_mouth_v3", "anatomy_detailed_cock_v3"],
      "preferred_kink": ["kink_deepthroat_gag_v2"]
    }
  }
}
```

---
