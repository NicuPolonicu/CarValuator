from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from carvaluator_scraper.dataset import prepare_dataframe_from_jsonl, save_dataframe_csv, save_json_report
from carvaluator_scraper.inference import predict_from_link
from carvaluator_scraper.normalize import load_jsonl, normalize_records, write_normalized_jsonl, write_report
from carvaluator_scraper.scrapers.autovit import AutovitScraper
from carvaluator_scraper.scrapers.mobilede import MobileDeBlockedError, MobileDeScraper
from carvaluator_scraper.train import load_training_frame, train_and_evaluate
from carvaluator_scraper.utils import write_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape used-car listing data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("scrape-search", help="Scrape search result pages.")
    search_parser.add_argument("site", choices=["autovit", "mobilede"])
    search_parser.add_argument("url", help="Search page URL")
    search_parser.add_argument("--pages", type=int, default=1, help="Number of pages to scrape")
    search_parser.add_argument("--delay", type=float, default=1.5, help="Delay between pages")
    search_parser.add_argument("--headful", action="store_true", help="Run browser with UI for mobile.de")
    search_parser.add_argument("--output", type=Path, help="Write rows as JSONL")
    search_parser.add_argument("--browser-channel", default="msedge", help="Browser channel for mobile.de")

    detail_parser = subparsers.add_parser("scrape-detail", help="Scrape one listing detail page.")
    detail_parser.add_argument("site", choices=["autovit"])
    detail_parser.add_argument("url", help="Listing detail URL")

    normalize_parser = subparsers.add_parser("normalize", help="Normalize and deduplicate JSONL data.")
    normalize_parser.add_argument("inputs", nargs="+", type=Path, help="Input JSONL files")
    normalize_parser.add_argument("--output", required=True, type=Path, help="Normalized JSONL output")
    normalize_parser.add_argument(
        "--drop-fuzzy-duplicates",
        action="store_true",
        help="Also drop likely duplicate rows using a conservative vehicle fingerprint",
    )
    normalize_parser.add_argument("--report", type=Path, help="Optional JSON report output")

    csv_parser = subparsers.add_parser("export-csv", help="Convert raw or normalized JSONL into CSV.")
    csv_parser.add_argument("inputs", nargs="+", type=Path, help="Input JSONL files")
    csv_parser.add_argument("--output", required=True, type=Path, help="CSV output path")
    csv_parser.add_argument(
        "--drop-fuzzy-duplicates",
        action="store_true",
        help="Also drop likely duplicate rows using a conservative vehicle fingerprint",
    )
    csv_parser.add_argument("--report", type=Path, help="Optional JSON report output")

    train_parser = subparsers.add_parser("train-models", help="Train regression models from CSV.")
    train_parser.add_argument("input_csv", type=Path, help="Prepared CSV dataset")
    train_parser.add_argument("--output-dir", required=True, type=Path, help="Directory for metrics, plots, and predictions")
    train_parser.add_argument("--random-state", type=int, default=42, help="Random seed for train/test split")
    train_parser.add_argument("--test-size", type=float, default=0.2, help="Test split fraction")
    train_parser.add_argument("--feature-selection-alpha", type=float, default=0.05, help="P-value threshold for feature significance")
    train_parser.add_argument("--min-pearson", type=float, default=0.05, help="Minimum absolute Pearson correlation for numeric features")
    train_parser.add_argument("--min-cramers-v", type=float, default=0.25, help="Minimum Cramer's V for categorical features")
    train_parser.add_argument("--disable-feature-selection", action="store_true", help="Train on all non-empty features without significance filtering")
    train_parser.add_argument("--log-target", action="store_true", help="Train on log1p(price_eur) and convert predictions back to EUR")

    predict_parser = subparsers.add_parser("predict-from-link", help="Predict fair price from one listing URL.")
    predict_parser.add_argument("site", choices=["autovit"], help="Listing site")
    predict_parser.add_argument("url", help="Listing URL")
    predict_parser.add_argument("--model-bundle", required=True, type=Path, help="Path to saved model bundle (.joblib)")
    predict_parser.add_argument("--threshold-percent", type=float, default=15.0, help="Percent threshold for fair / too low / too high verdict")

    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "scrape-search":
        if args.site == "autovit":
            scraper = AutovitScraper()
            rows = scraper.scrape_search(args.url, pages=args.pages, delay_seconds=args.delay)
        else:
            scraper = MobileDeScraper(headless=not args.headful, channel=args.browser_channel)
            try:
                rows = scraper.scrape_search(args.url, pages=args.pages, delay_seconds=args.delay)
            except MobileDeBlockedError as exc:
                parser.error(str(exc))
                return

        if args.output:
            write_jsonl(args.output, rows)
            print(f"Wrote {len(rows)} rows to {args.output}")
            return

        print(json.dumps([row.to_dict() for row in rows], ensure_ascii=False, indent=2))
        return

    if args.command == "scrape-detail":
        scraper = AutovitScraper()
        row = scraper.scrape_detail(args.url)
        print(json.dumps(row.to_dict(), ensure_ascii=False, indent=2))
        return

    if args.command == "normalize":
        rows: list[dict[str, object]] = []
        for path in args.inputs:
            rows.extend(load_jsonl(path))
        normalized_rows, report = normalize_records(
            rows,
            drop_fuzzy_duplicates=args.drop_fuzzy_duplicates,
        )
        write_normalized_jsonl(args.output, normalized_rows)
        if args.report:
            write_report(args.report, report)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return

    if args.command == "export-csv":
        frame, report = prepare_dataframe_from_jsonl(
            args.inputs,
            drop_fuzzy_duplicates=args.drop_fuzzy_duplicates,
        )
        save_dataframe_csv(frame, args.output)
        if args.report:
            save_json_report(report.to_dict(), args.report)
        print(json.dumps({**report.to_dict(), "csv_rows": int(len(frame)), "csv_output": str(args.output)}, ensure_ascii=False, indent=2))
        return

    if args.command == "train-models":
        frame = load_training_frame(args.input_csv)
        report = train_and_evaluate(
            frame,
            output_dir=args.output_dir,
            random_state=args.random_state,
            test_size=args.test_size,
            feature_selection_alpha=args.feature_selection_alpha,
            min_abs_pearson=args.min_pearson,
            min_cramers_v=args.min_cramers_v,
            disable_feature_selection=args.disable_feature_selection,
            log_target=args.log_target,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    if args.command == "predict-from-link":
        prediction = predict_from_link(
            site=args.site,
            url=args.url,
            model_bundle_path=args.model_bundle,
            threshold_percent=args.threshold_percent,
        )
        print(json.dumps(prediction.to_dict(), ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
