import hashlib
import mimetypes
from io import BytesIO
from typing import Any

import aioboto3
import httpx
from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential

from manga_scraper.config import settings
from manga_scraper.core.logging import get_logger

logger = get_logger("storage")


class ImageStorage:
    """S3/MinIO image storage handler."""

    def __init__(self):
        self.session = aioboto3.Session()
        self._http_client: httpx.AsyncClient | None = None

    async def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "image/*,*/*;q=0.9",
                    "Referer": "https://asuracomic.net/",
                },
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()

    def _get_s3_config(self) -> dict[str, Any]:
        """Get S3 client configuration."""
        config = {
            "service_name": "s3",
            "aws_access_key_id": settings.s3_access_key,
            "aws_secret_access_key": settings.s3_secret_key,
            "region_name": settings.s3_region,
        }
        if settings.s3_endpoint_url:
            config["endpoint_url"] = settings.s3_endpoint_url
        return config

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def download_and_store(
        self,
        source_url: str,
        series_id: int,
        chapter_id: int,
        page_number: int,
        optimize: bool = True,
    ) -> dict[str, Any]:
        """
        Download image from source and store to S3.
        
        Returns:
            {
                "path": str,  # S3 object key
                "url": str,   # Public URL
                "size": int,  # File size in bytes
                "content_type": str,
            }
        """
        client = await self.get_http_client()

        # Download image
        response = await client.get(source_url)
        response.raise_for_status()

        content = response.content
        content_type = response.headers.get("content-type", "image/jpeg")

        # Detect actual content type from image
        try:
            img = Image.open(BytesIO(content))
            fmt = img.format or "JPEG"
            content_type = f"image/{fmt.lower()}"

            # Optimize if requested
            if optimize:
                content, content_type = self._optimize_image(img)

        except Exception as e:
            logger.warning("image_process_failed", url=source_url, error=str(e))

        # Generate storage path
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        path = f"series/{series_id}/chapters/{chapter_id}/{page_number:04d}{ext}"

        # Upload to S3
        async with self.session.client(**self._get_s3_config()) as s3:
            await s3.put_object(
                Bucket=settings.s3_bucket_name,
                Key=path,
                Body=content,
                ContentType=content_type,
                CacheControl="public, max-age=31536000",  # 1 year cache
            )

        # Generate URL
        if settings.s3_endpoint_url:
            url = f"{settings.s3_endpoint_url}/{settings.s3_bucket_name}/{path}"
        else:
            url = f"https://{settings.s3_bucket_name}.s3.{settings.s3_region}.amazonaws.com/{path}"

        logger.debug(
            "image_stored",
            path=path,
            size=len(content),
            content_type=content_type,
        )

        return {
            "path": path,
            "url": url,
            "size": len(content),
            "content_type": content_type,
        }

    def _optimize_image(
        self,
        img: Image.Image,
        max_width: int = 1200,
        quality: int = 85,
    ) -> tuple[bytes, str]:
        """
        Optimize image for storage.
        - Convert to WebP for better compression
        - Resize if too large
        - Strip metadata
        """
        # Convert to RGB if necessary (for PNG with transparency)
        if img.mode in ("RGBA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if too wide
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

        # Save as WebP
        buffer = BytesIO()
        img.save(buffer, format="WEBP", quality=quality, method=4)
        buffer.seek(0)

        return buffer.read(), "image/webp"

    async def delete_image(self, path: str) -> None:
        """Delete image from S3."""
        async with self.session.client(**self._get_s3_config()) as s3:
            await s3.delete_object(
                Bucket=settings.s3_bucket_name,
                Key=path,
            )

    async def delete_chapter_images(self, series_id: int, chapter_id: int) -> int:
        """Delete all images for a chapter."""
        prefix = f"series/{series_id}/chapters/{chapter_id}/"
        deleted = 0

        async with self.session.client(**self._get_s3_config()) as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=settings.s3_bucket_name,
                Prefix=prefix,
            ):
                if "Contents" not in page:
                    continue

                objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
                if objects:
                    await s3.delete_objects(
                        Bucket=settings.s3_bucket_name,
                        Delete={"Objects": objects},
                    )
                    deleted += len(objects)

        logger.info("chapter_images_deleted", series_id=series_id, chapter_id=chapter_id, count=deleted)
        return deleted

    async def ensure_bucket_exists(self) -> None:
        """Create bucket if it doesn't exist."""
        async with self.session.client(**self._get_s3_config()) as s3:
            try:
                await s3.head_bucket(Bucket=settings.s3_bucket_name)
            except Exception:
                await s3.create_bucket(
                    Bucket=settings.s3_bucket_name,
                    CreateBucketConfiguration={
                        "LocationConstraint": settings.s3_region,
                    } if settings.s3_region != "us-east-1" else {},
                )
                logger.info("bucket_created", bucket=settings.s3_bucket_name)

                # Set bucket policy for public read (MinIO)
                if settings.s3_endpoint_url:
                    policy = {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"AWS": "*"},
                                "Action": ["s3:GetObject"],
                                "Resource": [f"arn:aws:s3:::{settings.s3_bucket_name}/*"],
                            }
                        ],
                    }
                    import json
                    await s3.put_bucket_policy(
                        Bucket=settings.s3_bucket_name,
                        Policy=json.dumps(policy),
                    )
