
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description="Update with Host Machine IP")
parser.add_argument(
    "-ip", "--ip",
    required=True,
    help="EXT-IP"
)
args = parser.parse_args()
EXT_IP = args.ip


def process_file(input_path, output_path):
    with open(input_path.absolute(), "r", encoding="utf-8") as f:
        content = f.read()

    new_content = content.replace("<EXT_IP>", EXT_IP)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_content)


# Process both files
process_file(Path("template/turnserver.conf"), Path("turnserver.conf"))
process_file(Path("template/chat.html"), Path("public/chat.html"))
process_file(Path("template/voice.html"), Path("public/voice.html"))
