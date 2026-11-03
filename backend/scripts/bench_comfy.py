"""Benchmark ComfyUI : python bench_comfy.py <variante> — temps par nœud (websocket) + copie de la vidéo dans ./out.

Usage (ComfyUI lancé sur 127.0.0.1:8188, dépendances httpx et websockets) :
    PROMPT_FILE=prompt.txt SEED=123456 TAG=_essai python bench_comfy.py H
Variantes : B (14B tel que livré, 480×832, sans ESRGAN), C (384×672), H (320×576), I (Flux puis I2V), D (NAG), F (LTX), G (Wan 1.3B).
Le fichier prompt (PROMPT_FILE, « prompt.txt » par défaut) est lu à côté du script ; les sorties vont dans ./out.
Script de mesure : il n'est pas importé par l'application ; il lit le workflow T2V livré dans ../workflows.
"""
import asyncio
import copy
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import httpx
import websockets

BASE = "http://127.0.0.1:8188"
COMFY_OUT = Path("/Users/mouhamadoudioufcisse/Documents/projet/stabledifusion/ComfyUI/output")
WF14 = json.load(open(Path(__file__).resolve().parents[1] / "workflows" / "comfyui-wan22-14b-t2v.json"))
PROMPT = open(Path(__file__).parent / os.environ.get("PROMPT_FILE", "prompt.txt")).read().strip()
SEED, FRAMES = int(os.environ.get("SEED", 123456)), 49
TAG = os.environ.get("TAG", "")
COMFY_IN = COMFY_OUT.parent / "input"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def lowres(w, width, height):
    w["11"]["inputs"].update(width=width, height=height)
    return w


NEGATIVE_EN = ("human hands, fingers, arm reaching in from outside, tentacle outside the jar, deformed, extra limbs, "
               "melting, morphing, blurry, distorted, text, watermark, low quality, static, jitter")


def nag(w):
    w["10"]["inputs"]["text"] += "，" + NEGATIVE_EN
    w["5n"] = {"class_type": "NAGuidance", "inputs": {"model": ["5", 0], "nag_scale": 5.0, "nag_alpha": 0.5, "nag_tau": 1.5}}
    w["6n"] = {"class_type": "NAGuidance", "inputs": {"model": ["6", 0], "nag_scale": 5.0, "nag_alpha": 0.5, "nag_tau": 1.5}}
    w["12"]["inputs"]["model"], w["13"]["inputs"]["model"] = ["5n", 0], ["6n", 0]
    return w


def ltx(_):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ltxv-2b-0.9.8-distilled.safetensors"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "t5xxl_fp8_e4m3fn.safetensors", "type": "ltxv", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{PROMPT}}", "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE_EN, "clip": ["2", 0]}},
        "5": {"class_type": "LTXVConditioning", "inputs": {"positive": ["3", 0], "negative": ["4", 0], "frame_rate": 24}},
        "6": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": 512, "height": 896, "length": 73, "batch_size": 1}},
        "7": {"class_type": "LTXVScheduler", "inputs": {"steps": 8, "max_shift": 2.05, "base_shift": 0.95, "stretch": True, "terminal": 0.1, "latent": ["6", 0]}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "SamplerCustom", "inputs": {"model": ["1", 0], "add_noise": True, "noise_seed": "{{SEED}}", "cfg": 1.0,
              "positive": ["5", 0], "negative": ["5", 1], "sampler": ["8", 0], "sigmas": ["7", 0], "latent_image": ["6", 0]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["1", 2]}},
        "11": {"class_type": "ImageScale", "inputs": {"upscale_method": "lanczos", "width": 720, "height": 1248, "crop": "disabled", "image": ["10", 0]}},
        "12": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["11", 0], "frame_rate": 24, "loop_count": 0, "filename_prefix": "bench/ltx",
               "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 19, "save_metadata": False, "trim_to_audio": False, "pingpong": False, "save_output": True}},
    }


def wan13(_):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.1_t2v_1.3B_fp16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "4": {"class_type": "ModelSamplingSD3", "inputs": {"shift": 8.0, "model": ["1", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{PROMPT}}", "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": WF14["10"]["inputs"]["text"] + "，" + NEGATIVE_EN, "clip": ["2", 0]}},
        "7": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"width": 480, "height": 832, "length": "{{FRAMES}}", "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"seed": "{{SEED}}", "steps": 20, "cfg": 5.0, "sampler_name": "uni_pc", "scheduler": "simple",
              "denoise": 1.0, "model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "ImageScale", "inputs": {"upscale_method": "lanczos", "width": 720, "height": 1248, "crop": "disabled", "image": ["9", 0]}},
        "11": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["10", 0], "frame_rate": 16, "loop_count": 0, "filename_prefix": "bench/wan13",
               "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 19, "save_metadata": False, "trim_to_audio": False, "pingpong": False, "save_output": True}},
    }


def flux_then_i2v():
    """Étape 1 : image Flux 9:16 ; étape 2 : Wan 2.2 14B image→vidéo à partir d'elle (384×672, 49 images)."""
    flux = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux1-dev-Q4_K_S.gguf"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn.safetensors", "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["2", 0]}},
        "5": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["4", 0], "guidance": 3.5}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 576, "height": 1008, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"seed": SEED, "steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
              "model": ["1", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "bench/flux_start"}},
    }
    w = copy.deepcopy(WF14)
    w["1"]["inputs"]["unet_name"] = "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"
    w["2"]["inputs"]["unet_name"] = "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"
    w["3"]["inputs"]["lora_name"] = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
    w["4"]["inputs"]["lora_name"] = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"
    del w["11"]
    w["19"] = {"class_type": "LoadImage", "inputs": {"image": "bench_start.png"}}
    w["11"] = {"class_type": "WanImageToVideo", "inputs": {"positive": ["9", 0], "negative": ["10", 0], "vae": ["8", 0], "width": 384, "height": 672,
               "length": FRAMES, "batch_size": 1, "start_image": ["19", 0]}}
    for k in ("12", "13"):
        w[k]["inputs"].update(positive=["11", 0], negative=["11", 1])
    w["12"]["inputs"]["latent_image"] = ["11", 2]
    raw = json.dumps(w).replace('"{{SEED}}"', str(SEED)).replace("{{PROMPT}}", json.dumps(PROMPT)[1:-1])
    return [flux, json.loads(raw)]


VARIANTS = {
    "I": flux_then_i2v,
    "H": lambda w: lowres(w, 320, 576),
    "B": lambda w: w,
    "C": lambda w: lowres(w, 384, 672),
    "D": nag,
    "F": ltx,
    "G": wan13,
}


TWO_STEP = {'I'}


def build(name):
    w = VARIANTS[name](copy.deepcopy(WF14))
    raw = json.dumps(w).replace('"{{FRAMES}}"', str(FRAMES)).replace('"{{SEED}}"', str(SEED))
    raw = raw.replace('"{{WIDTH}}"', "480").replace('"{{HEIGHT}}"', "832")  # taille livrée ; lowres la remplace avant
    return json.loads(raw.replace("{{PROMPT}}", json.dumps(PROMPT)[1:-1]))


async def run_workflow(wf):
    """Exécute un workflow API ; renvoie (durée totale, durée par nœud, historique)."""
    cid = str(uuid.uuid4())
    names = {k: v["class_type"] for k, v in wf.items()}
    times, current, t0, t_cur = {}, None, None, None
    async with websockets.connect(f"ws://127.0.0.1:8188/ws?clientId={cid}", max_size=None) as ws:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{BASE}/prompt", json={"prompt": wf, "client_id": cid})
            if r.status_code != 200:
                raise SystemExit(f"ERREUR {r.text[:800]}")
            pid = r.json()["prompt_id"]
        async for msg in ws:
            if isinstance(msg, bytes):
                continue
            m = json.loads(msg)
            d = m.get("data", {})
            if d.get("prompt_id") not in (None, pid):
                continue
            now = time.time()
            if m["type"] == "execution_start":
                t0 = now
            if m["type"] == "executing":
                if current is not None:
                    times[current] = times.get(current, 0) + now - t_cur
                current, t_cur = d["node"], now
                if d["node"] is None:
                    break
            if m["type"] == "execution_error":
                raise SystemExit(f"ERREUR {d}")
    async with httpx.AsyncClient() as c:
        h = (await c.get(f"{BASE}/history/{pid}")).json()[pid]
    return time.time() - t0, {f"{k}:{names[k]}": round(v) for k, v in times.items() if v >= 1}, h


def output_file(h, kinds=("gifs", "videos", "images")):
    f = next(v for o in h["outputs"].values() for k in kinds for v in o.get(k, []))
    return COMFY_OUT / f["subfolder"] / f["filename"]


async def main(name):
    total, nodes, steps = 0, {}, {}
    wfs = VARIANTS[name]() if name in TWO_STEP else [build(name)]
    for i, wf in enumerate(wfs):
        t, n, h = await run_workflow(wf)
        total += t
        steps[f"etape{i+1}"] = round(t)
        nodes.update({f"{i+1}.{k}": v for k, v in n.items()})
        if i == 0 and len(wfs) > 1:  # image de départ de l'étape 2 : copiée dans le dossier d'entrée de ComfyUI
            shutil.copy(output_file(h), COMFY_IN / "bench_start.png")
            shutil.copy(output_file(h), OUT / f"{name}{TAG}.png")
    dst = OUT / f"{name}{TAG}.mp4"
    shutil.copy(output_file(h, ("gifs", "videos")), dst)
    res = {"variant": name + TAG, "total_s": round(total), **steps, "nodes": nodes}
    json.dump(res, open(OUT / f"{name}{TAG}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


asyncio.run(main(sys.argv[1]))
