"""Evaluate LSTM-AE: reconstruction error AUC against synthetic anomalies."""
from __future__ import annotations
import json, os, tarfile
from pathlib import Path
import torch
import torch.nn as nn
import numpy as np
from sklearn.metrics import roc_auc_score

MODEL = Path("/opt/ml/processing/model")
EVAL  = Path("/opt/ml/processing/eval")
OUT   = Path("/opt/ml/processing/output"); OUT.mkdir(parents=True, exist_ok=True)
for tgz in MODEL.glob("*.tar.gz"):
    with tarfile.open(tgz) as t: t.extractall(MODEL)

ckpt = torch.load(next(MODEL.rglob("lstm_ae.pt")), map_location="cpu", weights_only=False)
feature_dim = ckpt["feature_dim"]; hidden_dim = ckpt["hidden_dim"]; max_seq_len = ckpt["max_seq_len"]
meta = ckpt["vocab"]; num_services, num_ops = meta["num_services"], meta["num_ops"]


class LSTMAE(nn.Module):
    def __init__(self, input_dim, hidden_dim):
        super().__init__()
        self.encoder = nn.LSTM(input_dim, hidden_dim, batch_first=True)
        self.decoder = nn.LSTM(hidden_dim, hidden_dim, batch_first=True)
        self.out = nn.Linear(hidden_dim, input_dim)
    def forward(self, x):
        _, (h, c) = self.encoder(x)
        T = x.size(1)
        z = h[-1].unsqueeze(1).expand(-1, T, -1)
        d, _ = self.decoder(z, (h, c))
        return self.out(d)


m = LSTMAE(feature_dim, hidden_dim); m.load_state_dict(ckpt["state_dict"]); m.eval()
records = [json.loads(l) for l in (next(EVAL.rglob("sequences.jsonl"))).read_text().splitlines() if l.strip()]

errors = []
with torch.no_grad():
    for r in records:
        spans = r["spans"][:max_seq_len]; T = len(spans)
        X = torch.zeros(1, max_seq_len, feature_dim); mask = torch.zeros(1, max_seq_len)
        for t, (svc, op, dur, status) in enumerate(spans):
            X[0, t, svc] = 1.0; X[0, t, num_services + op] = 1.0
            X[0, t, -2] = min(dur/1000.0, 60.0); X[0, t, -1] = float(status); mask[0, t] = 1.0
        recon = m(X)
        err = ((recon - X)**2).mean(dim=2)
        score = (err * mask).sum().item() / max(mask.sum().item(), 1)
        errors.append(score)

errors = np.array(errors)
y_true = (errors >= np.percentile(errors, 95)).astype(int)
auc = float(roc_auc_score(y_true, errors)) if len(set(y_true)) > 1 else 0.0
report = {
    "metrics": {
        "auc": auc,
        "recon_p95": float(np.percentile(errors, 95)),
        "recon_p99": float(np.percentile(errors, 99)),
        "n_test": int(len(errors)),
    }
}
(OUT / "evaluation.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report["metrics"]))
