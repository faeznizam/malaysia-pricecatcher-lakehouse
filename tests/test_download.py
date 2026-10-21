import functools
import http.server
import threading
from pathlib import Path

import pytest

from pricecatcher import download as dl

FAKE_PARQUET = b"PAR1" + b"\x00" * 100 + b"PAR1"


@pytest.fixture
def server(tmp_path):
    """Serve a folder over local HTTP so tests never touch data.gov.my."""
    root = tmp_path / "remote"
    root.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_price_filename():
    assert dl.price_filename("2026-09") == "pricecatcher_2026-09.parquet"


@pytest.mark.parametrize("bad", ["2026-9", "2026-13", "202609", "Sept"])
def test_price_filename_rejects_bad_months(bad):
    with pytest.raises(ValueError):
        dl.price_filename(bad)


def test_plan_includes_lookups_by_default(tmp_path):
    plan = dl.plan_downloads(["2026-09", "2026-10"], tmp_path, "http://x")
    assert [dest.relative_to(tmp_path).as_posix() for _, dest in plan] == [
        "prices/pricecatcher_2026-09.parquet",
        "prices/pricecatcher_2026-10.parquet",
        "lookups/lookup_item.parquet",
        "lookups/lookup_premise.parquet",
    ]
    assert plan[0][0] == "http://x/pricecatcher_2026-09.parquet"


def test_plan_without_lookups(tmp_path):
    assert len(dl.plan_downloads(["2026-09"], tmp_path, include_lookups=False)) == 1


def test_main_downloads_then_skips(server, tmp_path, capsys):
    remote, url = server
    for name in ["pricecatcher_2026-09.parquet", *dl.LOOKUP_FILES]:
        (remote / name).write_bytes(FAKE_PARQUET)
    landing = tmp_path / "landing"
    args = ["--months", "2026-09", "--landing", str(landing), "--base-url", url]

    assert dl.main(args) == 0
    assert (landing / "prices" / "pricecatcher_2026-09.parquet").read_bytes() == FAKE_PARQUET
    assert (landing / "lookups" / "lookup_premise.parquet").exists()

    assert dl.main(args) == 0
    assert capsys.readouterr().out.count("skipped") == 3


def test_missing_month_fails_and_leaves_no_file(server, tmp_path):
    _, url = server
    landing = tmp_path / "landing"
    code = dl.main(["--months", "2030-01", "--no-lookups", "--landing", str(landing), "--base-url", url])
    assert code == 1
    assert list(landing.rglob("*.parquet*")) == []


def test_non_parquet_response_is_rejected(server, tmp_path):
    remote, url = server
    (remote / "pricecatcher_2026-09.parquet").write_text("<html>error page</html>")
    dest = tmp_path / "out.parquet"
    with pytest.raises(ValueError):
        dl.download(f"{url}/pricecatcher_2026-09.parquet", dest)
    assert not dest.exists()
    assert not Path(str(dest) + ".part").exists()
