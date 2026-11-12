"""Tests for spider aliases support in SpiderLoader."""

import sys
from pathlib import Path

import pytest

from scrapy.crawler import CrawlerRunner
from scrapy.http import Request
from scrapy.settings import Settings
from scrapy.spiderloader import SpiderLoader
from scrapy.spiders import Spider

SPIDER_A = """
from scrapy.spiders import Spider


class SpiderA(Spider):
    name = "spider_a"
    aliases = ["old_spider_a", "legacy_a"]
    allowed_domains = ["example.com"]
"""

SPIDER_B = """
from scrapy.spiders import Spider


class SpiderB(Spider):
    name = "spider_b"
    allowed_domains = ["example.org"]
"""


def _write_package(root: Path, package: str, modules: dict[str, str]) -> None:
    pkg_dir = root / package
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")
    for filename, source in modules.items():
        (pkg_dir / filename).write_text(source)


@pytest.fixture
def make_settings(tmp_path, monkeypatch):
    """Write spider modules into a fresh package and return its settings."""
    monkeypatch.syspath_prepend(str(tmp_path))
    packages = []

    def factory(modules: dict[str, str], package: str) -> Settings:
        _write_package(tmp_path, package, modules)
        packages.append(package)
        return Settings({"SPIDER_MODULES": [package]})

    yield factory

    for package in packages:
        for mod in [m for m in sys.modules if m.split(".")[0] == package]:
            sys.modules.pop(mod, None)


def test_load_by_alias(make_settings):
    settings = make_settings(
        {"spider_a.py": SPIDER_A, "spider_b.py": SPIDER_B}, "alias_pkg_load"
    )
    loader = SpiderLoader.from_settings(settings)
    spider_a = loader.load("spider_a")
    assert spider_a.__name__ == "SpiderA"
    assert loader.load("old_spider_a") is spider_a
    assert loader.load("legacy_a") is spider_a
    assert loader.load("spider_b").__name__ == "SpiderB"


def test_load_unknown_name(make_settings):
    settings = make_settings({"spider_a.py": SPIDER_A}, "alias_pkg_unknown")
    loader = SpiderLoader.from_settings(settings)
    with pytest.raises(KeyError, match="Spider not found: nope"):
        loader.load("nope")


def test_list_only_canonical_names(make_settings):
    settings = make_settings(
        {"spider_a.py": SPIDER_A, "spider_b.py": SPIDER_B}, "alias_pkg_list"
    )
    loader = SpiderLoader.from_settings(settings)
    assert set(loader.list()) == {"spider_a", "spider_b"}


def test_find_by_request_only_canonical_names(make_settings):
    settings = make_settings(
        {"spider_a.py": SPIDER_A, "spider_b.py": SPIDER_B}, "alias_pkg_find"
    )
    loader = SpiderLoader.from_settings(settings)
    assert loader.find_by_request(Request("http://example.com")) == ["spider_a"]
    assert loader.find_by_request(Request("http://example.org")) == ["spider_b"]
    assert loader.find_by_request(Request("http://example.net")) == []


def test_crawler_runner_loads_by_alias(make_settings):
    settings = make_settings({"spider_a.py": SPIDER_A}, "alias_pkg_runner")
    runner = CrawlerRunner(settings)
    crawler = runner.create_crawler("old_spider_a")
    assert issubclass(crawler.spidercls, Spider)
    assert crawler.spidercls.name == "spider_a"


def test_alias_clashing_with_spider_name(make_settings):
    spider_b = SPIDER_B.replace(
        'name = "spider_b"', 'name = "spider_b"\n    aliases = ["spider_a"]'
    )
    settings = make_settings(
        {"spider_a.py": SPIDER_A, "spider_b.py": spider_b}, "alias_pkg_nameclash"
    )
    with pytest.raises(ValueError, match="conflicting spider aliases"):
        SpiderLoader.from_settings(settings)


def test_alias_clashing_with_own_name(make_settings):
    spider_a = SPIDER_A.replace(
        'aliases = ["old_spider_a", "legacy_a"]', 'aliases = ["spider_a"]'
    )
    settings = make_settings({"spider_a.py": spider_a}, "alias_pkg_ownname")
    with pytest.raises(ValueError, match="clashes with the name"):
        SpiderLoader.from_settings(settings)


def test_alias_clashing_with_other_alias(make_settings):
    spider_b = SPIDER_B.replace(
        'name = "spider_b"', 'name = "spider_b"\n    aliases = ["old_spider_a"]'
    )
    settings = make_settings(
        {"spider_a.py": SPIDER_A, "spider_b.py": spider_b}, "alias_pkg_aliasclash"
    )
    with pytest.raises(ValueError, match="claimed by several spiders"):
        SpiderLoader.from_settings(settings)


def test_spiders_without_aliases_unchanged(make_settings):
    settings = make_settings({"spider_b.py": SPIDER_B}, "alias_pkg_noalias")
    loader = SpiderLoader.from_settings(settings)
    assert loader.list() == ["spider_b"]
    assert loader.load("spider_b").__name__ == "SpiderB"
    assert loader._aliases == {}


def test_aliases_default_value():
    assert Spider.aliases == ()

    class NoAliasesSpider(Spider):
        name = "no_aliases"

    assert NoAliasesSpider.aliases == ()
