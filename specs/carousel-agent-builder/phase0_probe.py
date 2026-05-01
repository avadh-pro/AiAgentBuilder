"""Phase 0 probe — verify OpenAI image-API access.

Reads OPENAI_API_KEY from environment. Tries gpt-image-2 first, falls back to
gpt-image-1 to distinguish "model not available" from "auth/quota broken".

Run:
    $env:OPENAI_API_KEY = "sk-..."; python phase0_probe.py
"""

import os
import sys
from openai import OpenAI


def probe(client: OpenAI, model_name: str) -> tuple[bool, str]:
    try:
        result = client.images.generate(
            model=model_name,
            prompt="A single red circle on a white background, minimalist.",
            size="1024x1024",
            n=1,
        )
        if result.data and len(result.data) > 0:
            item = result.data[0]
            if getattr(item, "url", None):
                return True, f"image URL returned (len={len(item.url)})"
            if getattr(item, "b64_json", None):
                return True, f"base64 image returned (len={len(item.b64_json)})"
            return True, "response returned but no url/b64_json field"
        return False, "empty result.data"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:300]}"


def main() -> int:
    print("=" * 60)
    print("OpenAI Image API — Phase 0 Access Probe")
    print("=" * 60)

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY not set in environment")
        return 2

    print(f"Key prefix: {key[:12]}... (suffix: ...{key[-4:]})")
    print()

    client = OpenAI()

    print("Probing gpt-image-2 ...")
    ok2, msg2 = probe(client, "gpt-image-2")
    print(f"  {'OK' if ok2 else 'FAIL'} — {msg2}")

    if ok2:
        print()
        print("=" * 60)
        print("RESULT: gpt-image-2 accessible. Proceed with spec as written.")
        print("=" * 60)
        return 0

    print()
    print("Falling back to gpt-image-1 to check baseline ...")
    ok1, msg1 = probe(client, "gpt-image-1")
    print(f"  {'OK' if ok1 else 'FAIL'} — {msg1}")

    print()
    print("=" * 60)
    if ok1:
        print("RESULT: gpt-image-2 NOT accessible to this account; gpt-image-1 OK.")
        print("Recommendation: build pipeline with fallback_model=gpt-image-1.")
        print("Swap to gpt-image-2 once your account is on the rollout.")
        return 1
    print("RESULT: Neither model accessible. Likely auth, quota, or org-verification issue.")
    print("Check: https://platform.openai.com/settings/organization/billing")
    print("Check: https://platform.openai.com/settings/organization/general")
    return 3


if __name__ == "__main__":
    sys.exit(main())
