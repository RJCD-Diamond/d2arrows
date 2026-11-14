import base64
import binascii
import io
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np

NPY_TYPE = "application/x-npy"
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", NPY_TYPE}

_FORMAT_INFO = {  # fmt -> (Pillow format, content type, extension)
    "png": ("PNG", "image/png", ".png"),
    "jpeg": ("JPEG", "image/jpeg", ".jpg"),
    "webp": ("WEBP", "image/webp", ".webp"),
}

ALLOWED_IMAGE_EXPORT_TYPES = Literal["png", "jpeg", "webp", "npy", "jpg"]

MAX_BYTES = 10 * 1024 * 1024  # 10 MB decoded


def _fit_dtype(
    arr: "np.ndarray", allow_16bit: bool, fmt: str, clip: bool = False
) -> "np.ndarray":
    """Cast an integer array to uint8 (or uint16 if allowed).

    Lossless when every value fits; otherwise raise, or saturate if clip=True.
    """
    import numpy as np

    if arr.dtype == np.uint8 or (allow_16bit and arr.dtype == np.uint16):
        return arr
    limit = "uint16 (0-65535)" if allow_16bit else "uint8 (0-255)"
    if not np.issubdtype(arr.dtype, np.integer):
        raise ValueError(
            f"dtype {arr.dtype} can't be stored as {fmt} (max {limit}); "
            "scale/convert it yourself or use fmt='npy'"
        )
    lo, hi = (int(arr.min()), int(arr.max())) if arr.size else (0, 0)
    if clip and (lo < 0 or hi > (65535 if allow_16bit else 255)):
        top = 65535 if allow_16bit else 255
        return np.clip(arr, 0, top).astype(np.uint16 if allow_16bit else np.uint8)
    if lo >= 0 and hi <= 255:
        return arr.astype(np.uint8)
    if allow_16bit and lo >= 0 and hi <= 65535:
        return arr.astype(np.uint16)
    raise ValueError(
        f"{arr.dtype} values range {lo}..{hi}, which doesn't fit {fmt} "
        f"(max {limit}); use fmt='npy' to keep the data exactly, "
        "or clip=True to saturate out-of-range values"
    )


class ImageData(BaseModel):
    filename: str = Field(..., examples=["photo.jpg"])
    content_type: str = Field(..., examples=["image/jpeg"])
    data: str = Field(..., description="Base64-encoded image bytes")
    caption: str | None = None

    @field_validator("content_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in ALLOWED_TYPES:
            raise ValueError(f"unsupported content_type {v!r}")
        return v

    @field_validator("data")
    @classmethod
    def check_base64(cls, v: str) -> str:
        # Strip an optional data-URL prefix like "data:image/png;base64,"
        if v.startswith("data:") and "," in v:
            v = v.split(",", 1)[1]
        try:
            raw = base64.b64decode(v, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError("data is not valid base64") from e
        if len(raw) > MAX_BYTES:
            raise ValueError(f"image exceeds {MAX_BYTES} bytes")
        return v

    def to_bytes(self) -> bytes:
        return base64.b64decode(self.data)

    @classmethod
    def from_file(
        cls, path: str, content_type: str, caption: str | None = None
    ) -> "ImageData":
        from pathlib import Path

        p = Path(path)
        return cls(
            filename=p.name,
            content_type=content_type,
            data=base64.b64encode(p.read_bytes()).decode("ascii"),
            caption=caption,
        )

    @classmethod
    def from_array(
        cls,
        arr: "np.ndarray",
        fmt: ALLOWED_IMAGE_EXPORT_TYPES = "png",
        filename: str | None = None,
        caption: str | None = None,
        quality: int = 90,
        clip: bool = False,
    ) -> "ImageData":
        """Build a payload from a NumPy array.

        fmt="png"  lossless; uint8 (gray/RGB/RGBA) or uint16 grayscale.
        fmt="jpeg" / "webp"  lossy; uint8 only.
        Other integer dtypes (uint32, int64...) are cast down losslessly when every
        value fits; to_array() then returns the smaller dtype.
        clip=True saturates out-of-range integers to the format max (e.g. detector
        mask values of 2**32-1 become 65535) instead of raising.
        fmt="npy"  exact dtype and shape preserved (floats, uint32, 3D stacks...).
        """
        import numpy as np

        arr = np.asarray(arr)
        buf = io.BytesIO()

        if fmt == "npy":
            np.save(buf, arr, allow_pickle=False)
            content_type, ext = NPY_TYPE, ".npy"
        else:
            from PIL import Image

            if fmt not in _FORMAT_INFO:
                raise ValueError(f"unknown fmt {fmt!r}")
            pil_fmt, content_type, ext = _FORMAT_INFO[fmt]

            if arr.ndim == 3 and arr.shape[2] == 1:
                arr = arr[:, :, 0]
            ok_shape = arr.ndim == 2 or (arr.ndim == 3 and arr.shape[2] in (3, 4))
            if not ok_shape:
                raise ValueError(f"shape {arr.shape} is not an image; use fmt='npy'")
            arr = _fit_dtype(
                arr, allow_16bit=(fmt == "png" and arr.ndim == 2), fmt=fmt, clip=clip
            )
            img = Image.fromarray(np.ascontiguousarray(arr))
            if fmt == "jpeg" and img.mode == "RGBA":
                raise ValueError("JPEG has no alpha channel; use png or drop alpha")
            save_kwargs = {"quality": quality} if fmt in ("jpeg", "webp") else {}
            img.save(buf, format=pil_fmt, **save_kwargs)

        return cls(
            filename=filename or f"image{ext}",
            content_type=content_type,
            data=base64.b64encode(buf.getvalue()).decode("ascii"),
            caption=caption,
        )

    def to_file(
        self, path: "str | Path", overwrite: bool = True, clip: bool = False
    ) -> "Path":
        """Write the image to a full file path, e.g. "out/frame_001.png".

        The extension picks the format (.png, .jpg/.jpeg, .webp, .npy). If it matches
        the payload's format the bytes are written unchanged; otherwise the data is
        converted (same rules as from_array; clip is passed through).
        Parent directories are created if needed.
        """
        from pathlib import Path

        dest = Path(path)
        ext = dest.suffix.lower()

        format = ext.replace(".", "")

        if (format not in ALLOWED_IMAGE_EXPORT_TYPES) or (
            format not in _FORMAT_INFO.keys()
        ):
            raise ValueError(
                f"{str(path)!r} needs a file extension, "
                "one of: {ALLOWED_IMAGE_EXPORT_TYPES}"
            )
        if dest.is_dir():
            raise IsADirectoryError(dest)
        if dest.exists() and not overwrite:
            raise FileExistsError(dest)

        fmt = format
        target_type = NPY_TYPE if fmt == "npy" else _FORMAT_INFO[fmt][1]
        if target_type == self.content_type:
            raw = self.to_bytes()
        else:
            raw = type(self).from_array(self.to_array(), fmt=fmt, clip=clip).to_bytes()  # type: ignore

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return dest

    def to_array(self) -> "np.ndarray":
        """Decode the payload back into a NumPy array."""
        import numpy as np

        raw = io.BytesIO(self.to_bytes())
        if self.content_type == NPY_TYPE:
            return np.load(raw, allow_pickle=False)
        from PIL import Image

        with Image.open(raw) as img:
            return np.asarray(img)


class UploadResult(BaseModel):
    filename: str
    size_bytes: int
    saved_to: str
