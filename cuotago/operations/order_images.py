"""Validate and normalize optional order photos before persistence."""
import io
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTO_BYTES = 6 * 1024 * 1024
MAX_PHOTO_PIXELS = 20000000


def normalize_photo(raw):
    if not raw or len(raw) > MAX_PHOTO_BYTES:
        raise ValueError('La foto debe pesar como maximo 6 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValueError('Usa una foto JPG, PNG o WebP.')
                if source.width * source.height > MAX_PHOTO_PIXELS:
                    raise ValueError('La foto es demasiado grande. Usa una imagen de hasta 20 megapixeles.')
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1000, 750), Image.Resampling.LANCZOS)
                out = io.BytesIO()
                image.save(out, 'WEBP', quality=82, method=4)
                return out.getvalue(), 'image/webp'
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('No se pudo leer la foto. Usa un JPG, PNG o WebP valido.') from None
