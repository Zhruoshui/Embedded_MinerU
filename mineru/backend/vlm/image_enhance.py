# Copyright (c) Opendatalab. All rights reserved.
import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger
from openai import OpenAI
from PIL import Image

from mineru.utils.enum_class import ContentType, BlockType

MAX_IMAGE_DIMENSION = 2048
JPEG_QUALITY = 85
MAX_CONCURRENT_REQUESTS = 3
MAX_RETRIES = 3


def _build_image_description_prompt():
    return """请分析这张图片的内容，根据图片类型选择合适的输出格式：

1. 如果是普通照片/插图/场景图 → 用简洁的中文描述图中的关键视觉元素和内容
2. 如果是图表/数据可视化（柱状图、折线图、饼图等） → 提取数据并以markdown表格形式呈现
3. 如果是流程图/过程图/架构图 → 转换为mermaid代码块（用```mermaid包裹）
4. 如果是UI界面截图 → 描述界面布局和关键元素
5. 如果是表格截图 → 转换为markdown表格
6. 如果是技术示意图 → 描述结构和各组件关系

重要规则：
- 直接输出内容，不要添加任何前言、解释或后缀
- 保持简洁但信息完整
- 对于mermaid输出，使用```mermaid代码块包裹
- 对于markdown表格，确保表格格式正确
- 不要输出类似于"这张图片展示了"之类的开头语"""


def _preprocess_image(image_bytes: bytes) -> bytes:
    """Resize image to control token usage and re-encode as JPEG.

    Args:
        image_bytes: Raw image bytes.

    Returns:
        Processed JPEG bytes, resized if necessary.
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Convert to RGB first to avoid LANCZOS resampling errors with
    # palette (P) or alpha-channel (RGBA, LA) images, and to handle
    # CMYK images that occasionally appear in print-ready PDFs.
    if img.mode in ("RGBA", "P", "LA", "CMYK"):
        img = img.convert("RGB")

    width, height = img.size
    max_dim = max(width, height)
    if max_dim > MAX_IMAGE_DIMENSION:
        ratio = MAX_IMAGE_DIMENSION / max_dim
        new_size = (int(width * ratio), int(height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def _image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes as base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def _call_vision_api_sync(client: OpenAI, image_base64: str, config: dict) -> str:
    """Synchronously call the vision API with retry logic.

    Args:
        client: OpenAI client instance.
        image_base64: Base64-encoded image data.
        config: Image description configuration dict.

    Returns:
        The model's text response.

    Raises:
        Exception: If all retries are exhausted.
    """
    prompt = _build_image_description_prompt()

    api_params = {
        "model": config.get("model", "Qwen/Qwen3-VL-32B-Thinking"),
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}",
                        "detail": "high",
                    }
                },
                {
                    "type": "text",
                    "text": prompt,
                }
            ]
        }],
        "max_tokens": config.get("max_tokens", 4096),
        "temperature": config.get("temperature", 0.6),
        "stream": False,
    }

    # Qwen3-VL-32B-Thinking already has thinking mode built-in;
    # SiliconFlow API does not accept enable_thinking via extra_body for this model
    enable_thinking = config.get("enable_thinking", True)
    if enable_thinking and config.get("model", "").endswith("Thinking"):
        pass  # thinking is already enabled in the model name
    elif enable_thinking:
        api_params["extra_body"] = {"enable_thinking": True}

    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            response = client.chat.completions.create(**api_params)
            content = response.choices[0].message.content

            # Handle thinking mode output: strip <think>...</think> blocks
            if content and "</think>" in content:
                idx = content.index("</think>") + len("</think>")
                content = content[idx:].strip()

            return content if content else ""
        except Exception as e:
            retry_count += 1
            logger.warning(
                f"Vision API call failed (attempt {retry_count}/{MAX_RETRIES}): {e}"
            )

    raise Exception(f"Vision API call failed after {MAX_RETRIES} retries")


def _collect_image_spans(pdf_info_list: list):
    """Collect all image/chart spans that need description enhancement.

    Traverses preproc_blocks in all pages to find IMAGE and CHART type spans
    that have an image_path (i.e., have been saved to disk).

    Args:
        pdf_info_list: List of page info dicts.

    Returns:
        List of dicts with keys: span, image_path, type.
    """
    image_spans = []

    def _extract_spans_from_block(block):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_type = span.get("type")
                if span_type in (ContentType.IMAGE, ContentType.CHART):
                    image_path = span.get("image_path", "")
                    if image_path:
                        image_spans.append({
                            "span": span,
                            "image_path": image_path,
                            "type": span_type,
                        })

    for page_info in pdf_info_list:
        for block in page_info.get("preproc_blocks", []):
            block_type = block.get("type")
            if block_type in (BlockType.IMAGE, BlockType.CHART):
                # Two-layer structure: image -> blocks -> image_body -> lines -> spans
                for child in block.get("blocks", []):
                    if child.get("type") in (BlockType.IMAGE_BODY, BlockType.CHART_BODY):
                        _extract_spans_from_block(child)
            elif block_type in (BlockType.IMAGE_BODY, BlockType.CHART_BODY):
                # Flat structure: image_body -> lines -> spans
                _extract_spans_from_block(block)
    return image_spans


def _load_image_bytes(image_path: str, image_writer) -> bytes:
    """Load image bytes from the image_writer's storage.

    Tries to locate the image file using the writer's parent directory.
    Falls back to reading the image_path directly.

    Args:
        image_path: Relative or absolute path to the image.
        image_writer: DataWriter instance that saved the image (can be None).

    Returns:
        Raw image bytes.

    Raises:
        FileNotFoundError: If the image cannot be found.
    """
    if image_writer is not None:
        parent_dir = getattr(image_writer, '_parent_dir', '')
        if parent_dir:
            full_path = os.path.join(parent_dir, image_path)
            if os.path.exists(full_path):
                with open(full_path, 'rb') as f:
                    return f.read()

    # Fallback: try image_path directly
    if os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            return f.read()

    raise FileNotFoundError(f"Image file not found: {image_path}")


def _process_single_image(span_info: dict, client: OpenAI, config: dict, image_writer) -> None:
    """Process a single image: load, preprocess, call API, update span content.

    On any failure, the original span content is preserved and a warning is logged.

    Args:
        span_info: Dict with span, image_path, type keys.
        client: OpenAI client instance.
        config: Image description configuration dict.
        image_writer: DataWriter for reading image files.
    """
    span = span_info["span"]
    image_path = span_info["image_path"]
    span_type = span_info["type"]

    try:
        # Load image bytes
        image_bytes = _load_image_bytes(image_path, image_writer)

        # Preprocess and encode
        processed_bytes = _preprocess_image(image_bytes)
        image_base64 = _image_to_base64(processed_bytes)

        # Call API
        new_content = _call_vision_api_sync(client, image_base64, config)

        if new_content and new_content.strip():
            old_content = span.get("content", "")
            span["content"] = new_content.strip()
            logger.debug(
                f"Enhanced {span_type} description for {image_path}: "
                f"old_len={len(old_content)} -> new_len={len(new_content)}"
            )
        else:
            logger.warning(
                f"Empty response from vision API for {image_path}, "
                f"keeping original content"
            )
    except Exception as e:
        logger.warning(
            f"Failed to enhance image description for {image_path}: {e}, "
            f"keeping original content"
        )


def enhance_image_descriptions(pdf_info_list: list, image_writer) -> None:
    """Enhance image/chart descriptions using online vision model.

    Reads configuration from mineru.json's image-description-config section.
    Only runs if enable=True and api_key is configured.
    Images without a local VLM description will still be processed.

    Args:
        pdf_info_list: List of page info dicts with preproc_blocks.
        image_writer: DataWriter instance for reading saved image files (can be None).
    """
    # Lazy import to avoid circular dependency
    from mineru.utils.config_reader import get_image_description_config

    config = get_image_description_config()
    if config is None:
        return

    if not config.get("enable", False):
        return

    api_key = config.get("api_key", "")
    if not api_key:
        logger.warning(
            "image-description-config.enable=True but no api_key configured, "
            "skipping image description enhancement"
        )
        return

    base_url = config.get("base_url", "https://api.siliconflow.cn/v1")

    # Collect all image spans
    image_spans = _collect_image_spans(pdf_info_list)
    if not image_spans:
        logger.debug("No image/chart spans found for description enhancement")
        return

    logger.info(
        f"Enhancing descriptions for {len(image_spans)} image/chart spans "
        f"using online vision model"
    )

    # Create OpenAI client (one per enhance call, not reused across calls)
    client = OpenAI(api_key=api_key, base_url=base_url)

    # Process images concurrently using ThreadPoolExecutor
    max_workers = min(MAX_CONCURRENT_REQUESTS, len(image_spans))
    enhanced_count = 0
    failed_count = 0

    # Track original content to detect if enhancement actually changed it
    original_contents = {}
    for span_info in image_spans:
        original_contents[id(span_info["span"])] = span_info["span"].get("content", "")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_span = {}
        for span_info in image_spans:
            future = executor.submit(
                _process_single_image,
                span_info,
                client,
                config,
                image_writer,
            )
            future_to_span[future] = span_info

        for future in as_completed(future_to_span):
            span_info = future_to_span[future]
            try:
                future.result()
                new_content = span_info["span"].get("content", "").strip()
                original = original_contents.get(id(span_info["span"]), "")
                if new_content and new_content != original:
                    enhanced_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                logger.warning(
                    f"Image enhancement task failed for {span_info['image_path']}: {e}"
                )

    logger.info(
        f"Image description enhancement completed: "
        f"{enhanced_count} enhanced, {failed_count} failed/skipped"
    )
