"""OCR integration for scoreboard row images."""

from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

MODEL = "microsoft/trocr-base-printed"


def init_ocr(model_name=MODEL):
    """Load the TrOCR processor and model."""

    processor = TrOCRProcessor.from_pretrained(model_name)
    model = VisionEncoderDecoderModel.from_pretrained(model_name)
    return processor, model


def run_ocr(processor, model, row_paths):
    """Yield OCR text for each row image path."""

    for row_number, row_path in enumerate(row_paths, start=1):
        img = Image.open(row_path).convert("RGB")
        pixel_values = processor(img, return_tensors="pt").pixel_values
        generated_ids = model.generate(pixel_values, max_new_tokens=32)
        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

        yield row_number, text
