import base64
import anthropic

from tradebot.config.settings import ANTHROPIC_KEY, CLAUDE_MODEL, CLAUDE_TIMEOUT


def get_claude_client():
    if not ANTHROPIC_KEY:
        raise ValueError("ANTHROPIC_KEY 환경변수가 없습니다.")

    return anthropic.Anthropic(
        api_key=ANTHROPIC_KEY,
        timeout=CLAUDE_TIMEOUT
    )


def call_claude(prompt: str, max_tokens: int = 1000) -> str:
    try:
        client = get_claude_client()

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return response.content[0].text

    except Exception as e:
        return f"[Claude 호출 실패] {e}"


def call_claude_vision(image_bytes: bytes, prompt: str, max_tokens: int = 1000) -> str:
    try:
        client = get_claude_client()

        image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_data
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )

        return response.content[0].text

    except Exception as e:
        return f"[Claude Vision 호출 실패] {e}"
