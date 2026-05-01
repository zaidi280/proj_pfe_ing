
import json
import pandas as pd
from jiwer import wer
import numpy as np

# -----------------------------
# Flatten Nested JSON
# -----------------------------

def flatten_json(y, prefix=""):
    out = {}

    def flatten(x, name=""):
        if isinstance(x, dict):
            for a in x:
                flatten(x[a], f"{name}{a}.")

        elif isinstance(x, list):
            for i, a in enumerate(x):
                flatten(a, f"{name}{i}.")

        else:
            if x is None:
                x = ""

            out[name[:-1]] = str(x)

    flatten(y, prefix)
    return out


# -----------------------------
# Normalize Text
# -----------------------------

def normalize(text):
    if text is None:
        return ""

    text = str(text)
    text = text.lower()
    text = text.strip()

    return text


# -----------------------------
# Evaluation Function
# -----------------------------

def evaluate(predictions, ground_truths):

    rows = []

    total_exact = 0
    total_wer = 0
    total_fields = 0

    for idx, (pred, gt) in enumerate(zip(predictions, ground_truths)):

        pred_invoice = pred.get("invoice", {})
        gt_invoice = gt.get("invoice", {})

        pred_flat = flatten_json(pred_invoice)
        gt_flat = flatten_json(gt_invoice)

        keys = set(pred_flat.keys()).union(set(gt_flat.keys()))

        for key in keys:

            pred_val = normalize(pred_flat.get(key, ""))
            gt_val = normalize(gt_flat.get(key, ""))

            # Exact match
            exact = int(pred_val == gt_val)

            # Word error rate
            try:
                field_wer = wer(gt_val, pred_val)
            except:
                field_wer = 1

            rows.append({
                "invoice_id": idx,
                "field": key,
                "prediction": pred_val,
                "ground_truth": gt_val,
                "exact_match": exact,
                "wer": field_wer
            })

            total_exact += exact
            total_wer += field_wer
            total_fields += 1

    df = pd.DataFrame(rows)

    metrics = {
        "Exact Match Accuracy": total_exact / total_fields,
        "Average WER": total_wer / total_fields,
        "Total Fields": total_fields
    }

    return df, metrics


# -----------------------------
# Main
# -----------------------------

def main():

    print("Loading files...")

    with open("kimi_eval/invoice_pfe.invoices.json") as f:
        predictions = json.load(f)

    with open("kimi_eval/invoice_pfe_expected.invoices.json") as f:
        ground_truth = json.load(f)

    print("Evaluating...")

    df, metrics = evaluate(predictions, ground_truth)

    print("\n====================")
    print("Evaluation Results")
    print("====================")

    for k, v in metrics.items():
        print(f"{k}: {v:.4f}")

    print("\nSaving detailed results...")

    df.to_csv("evaluation_results.csv", index=False)

    print("Saved: evaluation_results.csv")

    # Field Accuracy
    field_accuracy = df.groupby("field")["exact_match"].mean()
    field_accuracy.to_csv("field_accuracy.csv")

    print("Saved: field_accuracy.csv")


if __name__ == "__main__":
    main()

