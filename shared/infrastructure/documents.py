"""Downloads the files MYPEs upload to Profile's bucket, over HTTP.

Profile's bucket allows anonymous reads (its ``fileUrl`` is public), so a plain
GET is enough. The base URL is this service's own way into the bucket, never
one that arrives in an event: an event only names the object key, which each
context's domain checks is under the folder it expects.

Shared by every context that reads an upload (the green certificates, the
ficha RUC); each one turns these failures into its own port's errors.
"""
import httpx


class DocumentMissingError(Exception):
    """The bucket has no such object, or refuses to serve it."""


class DocumentTooLargeError(Exception):
    """The object is larger than the caller accepts."""


class StorageUnavailableError(Exception):
    """The bucket did not answer, or answered with an error worth retrying."""


async def download_document(client: httpx.AsyncClient, object_key: str, max_bytes: int) -> bytes:
    """Download one object, stopping as soon as it is larger than allowed.

    Args:
        client (httpx.AsyncClient): A client whose ``base_url`` is the bucket's.
        object_key (str): The object's key, relative to the bucket.
        max_bytes (int): The largest file accepted.

    Returns:
        bytes: The file.

    Raises:
        DocumentMissingError: If the bucket answers 404 or 403.
        DocumentTooLargeError: If the file is larger than ``max_bytes``.
        StorageUnavailableError: If the bucket did not answer or answered another error.
    """
    try:
        async with client.stream("GET", object_key) as response:
            if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.FORBIDDEN):
                raise DocumentMissingError(object_key)
            if not response.is_success:
                raise StorageUnavailableError(f"The storage answered HTTP {response.status_code}")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise DocumentTooLargeError(object_key)
    except httpx.HTTPError as error:
        raise StorageUnavailableError(f"{type(error).__name__}: {error}") from error
    return bytes(content)
