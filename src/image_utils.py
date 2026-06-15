import base64
from pathlib import Path

import httpx


MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_SIZE_TEXT = "5MB"


class ImageTooLargeError(ValueError):
    pass


def _cleanup(path: Path) -> None:
    path.unlink(missing_ok=True)


async def download_image(url: str, dest: Path, max_bytes: int = MAX_IMAGE_BYTES) -> None:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("图片地址不可下载。")

    tmp = dest.with_name(f"{dest.name}.part")
    _cleanup(tmp)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type and not content_type.startswith("image/"):
                    raise ValueError("图片响应类型不正确。")
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    raise ImageTooLargeError(f"图片不能超过 {MAX_IMAGE_SIZE_TEXT}。")

                total = 0
                with tmp.open("wb") as file:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ImageTooLargeError(f"图片不能超过 {MAX_IMAGE_SIZE_TEXT}。")
                        file.write(chunk)
        if tmp.stat().st_size == 0:
            raise ValueError("图片内容为空。")
        tmp.replace(dest)
    except Exception:
        _cleanup(tmp)
        _cleanup(dest)
        raise


def read_image_base64(path: Path, max_bytes: int = MAX_IMAGE_BYTES) -> str:
    if path.stat().st_size > max_bytes:
        raise ImageTooLargeError(f"图片超过 {MAX_IMAGE_SIZE_TEXT}，不能直接发送。")
    return base64.b64encode(path.read_bytes()).decode("ascii")
