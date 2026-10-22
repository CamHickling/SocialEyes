"""Adding a study's images from a folder, the image check, and sources.csv."""
import csv
import shutil

from PIL import Image

from socialeyes.desktop import images as I


def test_files_match_slots_by_name_whatever_the_case_dashes_or_extension(example, tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    shutil.copy(example / "images" / "crit01_original.png", drop / "CRIT01-Original.PNG")
    Image.new("RGB", (540, 675), "red").save(drop / "crit01 retouched.jpg")     # a .jpg for the .png slot
    Image.new("RGB", (540, 675), "blue").save(drop / "holiday_photo.jpg")      # matches nothing
    (example / "images" / "crit01_retouched.png").unlink()                      # an empty slot
    m = I.match(example, drop)
    by_slot = {x["slot"]: x for x in m["matched"]}
    assert by_slot["images/crit01_original.png"]["exists"] is True
    assert by_slot["images/crit01_retouched.png"]["source"].endswith("crit01 retouched.jpg")
    assert [p.split("\\")[-1].split("/")[-1] for p in m["unmatched"]] == ["holiday_photo.jpg"]
    assert m["missing"] == []                                                   # the empty slot has a match

    r = I.copy_in(example, m["matched"])
    assert r["converted"] == ["images/crit01_retouched.png"] and r["kept"] == ["images/crit01_original.png"]
    with Image.open(example / "images" / "crit01_retouched.png") as im:
        r0, g0, b0 = im.getpixel((0, 0))[:3]
        assert im.format == "PNG" and r0 > 245 and g0 < 10 and b0 < 10      # red (the jpg was lossy)
    # a file already there is only replaced when asked
    before = (example / "images" / "crit01_original.png").read_bytes()
    I.copy_in(example, [{"source": str(drop / "holiday_photo.jpg"), "slot": "images/crit01_original.png"}])
    assert (example / "images" / "crit01_original.png").read_bytes() == before
    I.copy_in(example, [{"source": str(drop / "holiday_photo.jpg"), "slot": "images/crit01_original.png"}], replace=True)
    assert (example / "images" / "crit01_original.png").read_bytes() != before


def test_image_check_flags_shape_size_duplicates_and_mismatched_versions(example):
    Image.new("RGB", (400, 900), "white").save(example / "images" / "fill01.png")       # too tall, too small
    Image.new("RGB", (3000, 3750), "white").save(example / "images" / "fill02.png")     # far too large
    shutil.copy(example / "images" / "fill03.png", example / "images" / "fill04.png")   # the same picture twice
    Image.new("RGB", (600, 750), "white").save(example / "images" / "crit02_retouched.png")  # versions differ
    r = I.image_report(example)
    flags = {x["file"]: " | ".join(x["flags"]) for x in r["images"]}
    assert "taller than a feed post" in flags["images/fill01.png"] and "blurry" in flags["images/fill01.png"]
    assert "larger than needed" in flags["images/fill02.png"] and r["large"] == ["images/fill02.png"]
    assert "the same picture as images/fill03.png" in flags["images/fill04.png"]
    assert any("crit02" in n and "differ in size" in n for n in r["notes"])
    done = I.resize_large(example)
    with Image.open(example / "images" / "fill02.png") as im:
        assert max(im.size) == I.MAX_SIDE
    with Image.open(example / "originals" / "images" / "fill02.png") as im:
        assert im.size == (3000, 3750)                                                   # kept
    assert done["resized"] == ["images/fill02.png"]


def test_sources_csv_follows_the_study_and_keeps_what_was_typed(example):
    assert I.sources(example, create=False)["exists"] is False and not (example / I.SOURCES).exists()
    r = I.sources(example)
    assert r["files"] == r["added"] and r["complete"] == 0
    path = example / I.SOURCES
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    rows[0].update(source="Unsplash, photo 123", licence="Unsplash licence")
    rows[1]["source"] = "own photo"                                # no licence yet: not complete
    rows.append({"file": "images/retired_image.png", "source": "kept", "licence": "kept", "credit": "",
                 "consent": "", "notes": "no longer in the study"})
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=I.SOURCE_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    again = I.sources(example)
    assert again["added"] == 0 and again["complete"] == 1 and again["files"] == r["files"]
    kept = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert any(x["file"] == "images/retired_image.png" for x in kept)              # never removed
