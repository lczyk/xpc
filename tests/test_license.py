from pathlib import Path

__project_root__ = Path(__file__).parent.parent


def test_license() -> None:
    # Make sure the license file is correctly included in the source file

    license_file = __project_root__ / "LICENSE.txt"
    assert license_file.exists(), f"License file {license_file} not found."

    source_file = __project_root__ / "src" / "xpc" / "xpc.py"
    assert source_file.exists(), f"Source file {source_file} not found."

    # Make sure the license is included in the source file verbatim
    with open(license_file) as f:
        license_text = f.read()

    with open(source_file) as f:
        source_text = f.read()

    assert license_text in source_text, "License not found in source file."
