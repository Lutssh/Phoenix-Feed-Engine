"""
engines/ml_service/processor.py  (bridge to smart_ingestion)
Preserves the analyze_content() interface the Rust engine depends on.
"""
from smart_ingestion.ml_core.processor import get_processor


def analyze_content(data: dict):
    """
    Legacy interface — maps old task type strings to the new MLProcessor.
    Do not call this directly in new code; use smart_ingestion workers instead.
    """
    proc = get_processor()
    task = data.get("type")
    content = data.get("content", "")
    extra = data.get("extra_args", {})

    if task == "text_embedding":
        return proc.embed_text(content)

    elif task == "yolo":
        return proc.detect_objects(content)

    elif task == "whisper":
        return proc.transcribe_audio(content)

    elif task == "llava":
        # LLaVA is replaced — return CLIP frame embedding as a list[float]
        # The aggregator now stores this directly; string description is no longer needed.
        return proc.embed_video_frames(content)

    elif task == "clip_image":
        return proc.embed_image(content)

    elif task == "clip_video":
        return proc.embed_video_frames(content)

    elif task == "clip_text":
        return proc.text_to_clip_vector(content)

    elif task == "aggregation":
        import numpy as np
        visual_vec = np.array(proc.embed_video_frames(content))
        result = {"video_embedding": visual_vec.tolist()}
        caption = extra.get("caption", "")
        if caption:
            cap_vec = np.array(proc.text_to_clip_vector(caption))
            result["semantic_alignment_score"] = float(np.dot(visual_vec, cap_vec))
        else:
            result["semantic_alignment_score"] = 1.0
        return result

    else:
        raise ValueError(f"Unknown task type: {task}")
