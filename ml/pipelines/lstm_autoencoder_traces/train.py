"""LSTM autoencoder for trace span sequences."""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
import torch, torch.nn as nn, torch.optim as optim
from torch.utils.data import DataLoader, Dataset


class SpanSeqDataset(Dataset):
    def __init__(self, jsonl: Path, num_services: int, num_ops: int, max_len: int):
        self.records = [json.loads(l) for l in jsonl.read_text().splitlines() if l.strip()]
        self.feature_dim = num_services + num_ops + 2  # one-hot svc + one-hot op + dur_ms + status
        self.num_services, self.num_ops, self.max_len = num_services, num_ops, max_len

    def __len__(self): return len(self.records)
    def __getitem__(self, idx):
        spans = self.records[idx]["spans"][:self.max_len]
        T = len(spans)
        X = torch.zeros(self.max_len, self.feature_dim)
        mask = torch.zeros(self.max_len)
        for t, (svc, op, dur, status) in enumerate(spans):
            X[t, svc] = 1.0
            X[t, self.num_services + op] = 1.0
            X[t, -2] = min(dur / 1000.0, 60.0)  # cap at 60s
            X[t, -1] = float(status)
            mask[t] = 1.0
        return X, mask


class LSTMAE(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int):
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--hidden-dim", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--max-seq-len", type=int, default=64)
    args, _ = p.parse_known_args()

    train_dir = Path(os.environ["SM_CHANNEL_TRAIN"])
    meta_dir  = Path(os.environ["SM_CHANNEL_METADATA"])
    out_dir   = Path(os.environ["SM_MODEL_DIR"])
    meta = json.loads((meta_dir / "vocab.json").read_text())
    num_services, num_ops = meta["num_services"], meta["num_ops"]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ds = SpanSeqDataset(train_dir / "sequences.jsonl", num_services, num_ops, args.max_seq_len)
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=True, num_workers=2)

    model = LSTMAE(ds.feature_dim, args.hidden_dim).to(device)
    opt = optim.Adam(model.parameters(), lr=args.lr)
    mse = nn.MSELoss(reduction="none")

    for epoch in range(args.epochs):
        t0 = time.time(); total = 0.0; n = 0
        for X, mask in dl:
            X, mask = X.to(device), mask.to(device)
            recon = model(X)
            loss = (mse(recon, X).mean(dim=2) * mask).sum() / mask.sum().clamp_min(1)
            opt.zero_grad(); loss.backward(); opt.step()
            total += loss.item() * X.size(0); n += X.size(0)
        print(f"epoch {epoch+1}/{args.epochs} loss={total/max(n,1):.4f} ({time.time()-t0:.1f}s)")

    torch.save({
        "state_dict": model.state_dict(),
        "feature_dim": ds.feature_dim,
        "hidden_dim": args.hidden_dim,
        "max_seq_len": args.max_seq_len,
        "vocab": meta,
    }, out_dir / "lstm_ae.pt")


if __name__ == "__main__":
    main()
