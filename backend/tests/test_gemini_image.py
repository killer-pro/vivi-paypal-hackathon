"""Image de référence par Gemini (`generateContent`, réponse en image base64), transport simulé : aucun appel réseau."""
import base64
import json

import httpx
import pytest

from app.providers.base import Availability, ProviderError
from app.providers.gemini import DEFAULT_IMAGE_MODEL, IMAGE_PRICES, KEY_MISSING, GeminiImage, image_models

KEY = "AIza-secret-key-1234"
JPEG = b"\xff\xd8\xff\xe0JFIF-image"


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def image_response(data=JPEG, mime="image/jpeg", usage=None):
    parts = [{"text": "Voici l'image"}, {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}]
    return httpx.Response(200, json={
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
        "usageMetadata": usage or {"promptTokenCount": 22, "candidatesTokenCount": 1120},
    })


async def test_generate_returns_the_decoded_image_and_its_cost():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), key=req.headers.get("x-goog-api-key"), body=json.loads(req.content))
        return image_response()

    r = await GeminiImage(KEY, client(handler)).generate("chambre la nuit", model=DEFAULT_IMAGE_MODEL)
    assert seen["url"].endswith(f"/models/{DEFAULT_IMAGE_MODEL}:generateContent") and KEY not in seen["url"]
    assert seen["key"] == KEY
    assert seen["body"]["contents"][0]["parts"] == [{"text": "chambre la nuit"}]
    assert seen["body"]["generationConfig"] == {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}
    price_in, price_out = IMAGE_PRICES[DEFAULT_IMAGE_MODEL]
    assert (r.data, r.content_type, r.model) == (JPEG, "image/jpeg", DEFAULT_IMAGE_MODEL)
    assert r.cost_usd == pytest.approx((22 * price_in + 1120 * price_out) / 1_000_000)


async def test_content_type_follows_the_real_image_bytes_not_the_announced_mime():
    # Gemini annonce parfois image/png pour un JPEG : l'extension du fichier stocké et ffmpeg suivent le type réel.
    r = await GeminiImage(KEY, client(lambda req: image_response(JPEG, mime="image/png"))).generate(
        "p", model=DEFAULT_IMAGE_MODEL)
    assert r.content_type == "image/jpeg"


async def test_without_key_nothing_is_sent():
    def handler(req):
        raise AssertionError("aucune requête attendue sans clé")

    image = GeminiImage("", client(handler))
    with pytest.raises(ProviderError) as e:
        await image.generate("p", model=DEFAULT_IMAGE_MODEL)
    assert str(e.value) == KEY_MISSING and not e.value.retryable
    assert set((await image.image_availability()).values()) == {Availability(False, KEY_MISSING)}
    assert await image.health() is False


@pytest.mark.parametrize(("body", "reason"), [
    ({"candidates": [{"content": {"parts": [{"text": "Je ne peux pas"}]}, "finishReason": "IMAGE_SAFETY"}]},
     "IMAGE_SAFETY"),
    ({"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}, "SAFETY"),
    ({}, "réponse vide"),
])
async def test_response_without_image_is_a_clear_non_retryable_error(body, reason):
    image = GeminiImage(KEY, client(lambda req: httpx.Response(200, json=body)))
    with pytest.raises(ProviderError) as e:
        await image.generate("p", model=DEFAULT_IMAGE_MODEL)
    assert str(e.value).startswith("gemini: aucune image") and reason in str(e.value) and not e.value.retryable


async def test_returned_image_type_must_be_an_image():
    image = GeminiImage(KEY, client(lambda req: image_response(b"<svg/>", "image/svg+xml")))
    with pytest.raises(ProviderError, match="type d'image inattendu"):
        await image.generate("p", model=DEFAULT_IMAGE_MODEL)


@pytest.mark.parametrize(("status", "retryable"), [(404, False), (400, False), (429, True), (503, True)])
async def test_http_errors(status, retryable):
    image = GeminiImage(KEY, client(lambda req: httpx.Response(status, text="models/x is not found")))
    with pytest.raises(ProviderError) as e:
        await image.generate("p", model="gemini-retired-image")
    assert e.value.retryable is retryable and str(e.value).startswith(f"gemini: HTTP {status}")


async def test_catalogue_lists_the_configured_model_first():
    assert image_models("gemini-9-image") == ["gemini-9-image", *IMAGE_PRICES]
    assert image_models(DEFAULT_IMAGE_MODEL) == list(dict.fromkeys([DEFAULT_IMAGE_MODEL, *IMAGE_PRICES]))
    image = GeminiImage(KEY, client(lambda req: None), model="gemini-9-image")
    assert list(await image.image_availability()) == image_models("gemini-9-image")
    assert set((await image.image_availability()).values()) == {Availability(True)}


async def test_unknown_model_is_priced_with_the_most_expensive_entry():
    r = await GeminiImage(KEY, client(lambda req: image_response())).generate("p", model="gemini-9-image")
    price_in, price_out = max(IMAGE_PRICES.values())
    assert r.cost_usd == pytest.approx((22 * price_in + 1120 * price_out) / 1_000_000)


async def test_reference_images_are_sent_before_the_prompt_as_inline_data():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(body=json.loads(req.content))
        return image_response()

    png = b"\x89PNG\r\n\x1a\nxx"
    await GeminiImage(KEY, client(handler)).generate("dans la rue", model=DEFAULT_IMAGE_MODEL, references=[png, JPEG])
    assert seen["body"]["contents"][0]["parts"] == [
        {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png).decode()}},
        {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(JPEG).decode()}},
        {"text": "dans la rue"}]


def test_image_cost_is_estimated_from_the_output_price_and_the_tokens_of_one_image():
    from app.providers.gemini import IMAGE_OUTPUT_TOKENS, estimate_image_cost
    assert estimate_image_cost(DEFAULT_IMAGE_MODEL) == IMAGE_PRICES[DEFAULT_IMAGE_MODEL][1] * IMAGE_OUTPUT_TOKENS / 1e6
    assert estimate_image_cost("inconnu") == max(p[1] for p in IMAGE_PRICES.values()) * IMAGE_OUTPUT_TOKENS / 1e6
