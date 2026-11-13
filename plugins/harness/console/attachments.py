"""이어서 요청에 붙이는 첨부(이미지·PDF)를 검사하고 stream-json user 메시지의 content 블록으로 바꾼다 (#860).

화면(attach.js)도 같은 한도로 먼저 거르지만, 서버가 형식·크기를 다시 검사한다. 대화 기록에는 원본(base64)을 남기지 않고 이름·형식·크기만 남긴다.
"""
from __future__ import annotations

import base64
import binascii

MAX_COUNT = 5                       # 한 번에 붙이는 개수
MAX_IMAGE = 5 << 20                 # 이미지 한 장. Claude API 가 이미지 한 장을 5MB 까지 받는다
MAX_PDF = 20 << 20                  # PDF 한 개. 요청 본문 상한(32MB, base64 로 4/3 배) 안에 든다
MAX_TOTAL = 20 << 20                # 한 번에 보내는 첨부 합계(원본 크기). base64 로 약 26.7MB
NAME_MAX = 100

# 허용 형식과 파일 첫머리 확인(확장자·이름이 아니라 내용으로 본다)
_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),  # 8~12 바이트가 WEBP 인지는 따로 본다
    "application/pdf": (b"%PDF-",),
}


class AttachmentError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _clean_name(name) -> str:
    text = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return "".join(ch for ch in text if ch.isprintable())[:NAME_MAX] or "첨부"


def _matches(media_type: str, raw: bytes) -> bool:
    if not any(raw.startswith(sig) for sig in _SIGNATURES[media_type]):
        return False
    return media_type != "image/webp" or raw[8:12] == b"WEBP"


def parse(items) -> list[dict]:
    """요청 본문의 attachments 를 검사해 [{name, media_type, data, size}] 로 돌려준다. 없으면 빈 목록. 어긋나면 AttachmentError."""
    if items in (None, []):
        return []
    if not isinstance(items, list):
        raise AttachmentError("attachments 는 목록이어야 해.")
    if len(items) > MAX_COUNT:
        raise AttachmentError(f"첨부는 한 번에 {MAX_COUNT}개까지 보낼 수 있어.")
    out, total = [], 0
    for item in items:
        if not isinstance(item, dict):
            raise AttachmentError("첨부 항목 모양이 올바르지 않아.")
        media_type, data = item.get("media_type"), item.get("data")
        name = _clean_name(item.get("name"))
        if media_type not in _SIGNATURES:
            raise AttachmentError(f"{name}: 이미지(png·jpg·gif·webp)와 PDF 만 보낼 수 있어.")
        if not isinstance(data, str) or not data:
            raise AttachmentError(f"{name}: 내용이 비어 있어.")
        limit = MAX_PDF if media_type == "application/pdf" else MAX_IMAGE
        if len(data) > limit * 4 // 3 + 8:  # 디코드하기 전에 크기부터 본다
            raise AttachmentError(f"{name}: 너무 커. {'PDF 는 20MB' if media_type == 'application/pdf' else '이미지는 한 장에 5MB'}까지야.", 413)
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise AttachmentError(f"{name}: 파일 내용을 읽지 못했어(base64 가 아니야).")
        if len(raw) > limit:
            raise AttachmentError(f"{name}: 너무 커. {'PDF 는 20MB' if media_type == 'application/pdf' else '이미지는 한 장에 5MB'}까지야.", 413)
        if not _matches(media_type, raw):
            raise AttachmentError(f"{name}: 파일 내용이 {media_type} 가 아니야.")
        total += len(raw)
        if total > MAX_TOTAL:
            raise AttachmentError("첨부 합계가 너무 커. 합쳐서 20MB 까지야.", 413)
        out.append({"name": name, "media_type": media_type, "data": data, "size": len(raw)})
    return out


def content_blocks(text: str, attachments: list[dict]) -> list[dict]:
    """첨부 블록(이미지 image, PDF document)을 먼저, 글(text)을 뒤에 둔 content 배열. 글이 없으면 text 블록은 뺀다."""
    blocks = []
    for a in attachments:
        kind = "document" if a["media_type"] == "application/pdf" else "image"
        blocks.append({"type": kind, "source": {"type": "base64", "media_type": a["media_type"], "data": a["data"]}})
    if text:
        blocks.append({"type": "text", "text": text})
    return blocks


def meta(attachments: list[dict]) -> list[dict]:
    """대화 기록에 남길 것. base64 원본은 넣지 않는다."""
    return [{"name": a["name"], "type": a["media_type"], "size": a["size"]} for a in attachments]
