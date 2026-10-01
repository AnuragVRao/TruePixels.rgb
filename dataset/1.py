import zipfile
import os
import shutil

ZIP_FILE = "synthbuster.zip"
OUTPUT_DIR = "synthbuster_1k"
IMAGES_PER_MODEL = 111

os.makedirs(OUTPUT_DIR, exist_ok=True)

with zipfile.ZipFile(ZIP_FILE, "r") as z:
    files = z.namelist()

    # Find the top-level model folders automatically
    models = {}

    for f in files:
        if f.endswith("/"):
            continue

        parts = f.replace("\\", "/").split("/")

        if len(parts) >= 2:
            model = parts[1]

            # Only count image files
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                models.setdefault(model, []).append(f)

    print("Models found:")
    for model, image_files in models.items():
        print(f"  {model}: {len(image_files)} images")

    print()

    for model, image_files in models.items():

        # Take exactly 111
        selected = sorted(image_files)[:IMAGES_PER_MODEL]

        model_name = model.replace(" ", "_")
        output_model_dir = os.path.join(OUTPUT_DIR, model_name)

        os.makedirs(output_model_dir, exist_ok=True)

        print(f"Extracting {model}: {len(selected)} images")

        for i, file_path in enumerate(selected, 1):

            extension = os.path.splitext(file_path)[1]

            output_file = os.path.join(
                output_model_dir,
                f"{i:04d}{extension}"
            )

            with z.open(file_path) as source:
                with open(output_file, "wb") as target:
                    shutil.copyfileobj(source, target)

print("\nDone!")