"""Tiny Recursive Model for equational implication.

Sketch only - skeleton for Phase 2. Refine after Phase 0 baseline.
"""
import torch
import torch.nn as nn


class TRMBlock(nn.Module):
    def __init__(self, d_model: int, n_heads: int, d_ff: int):
        super().__init__()
        self.attn = nn.MultiheadAttention(d_model, n_heads, batch_first=True)
        self.ln1 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, d_ff), nn.GELU(), nn.Linear(d_ff, d_model)
        )
        self.ln2 = nn.LayerNorm(d_model)

    def forward(self, x):
        h, _ = self.attn(x, x, x, need_weights=False)
        x = self.ln1(x + h)
        x = self.ln2(x + self.ff(x))
        return x


class TRM(nn.Module):
    """Recursive latent reasoner.

    Inputs:
      eq_tokens: (B, T_in) token ids for "Eq1 :: Eq2"
      n_recursion: number of latent refinement steps

    Output:
      cert_logits: (B, T_out, V) over Lean tokens
    """

    def __init__(
        self,
        vocab_size: int = 8192,
        d_model: int = 256,
        n_heads: int = 8,
        d_ff: int = 1024,
        n_layers: int = 2,
        max_len: int = 4096,
    ):
        super().__init__()
        self.tok_emb = nn.Embedding(vocab_size, d_model)
        self.pos_emb = nn.Embedding(max_len, d_model)
        self.latent = nn.Parameter(torch.randn(1, 32, d_model) * 0.02)
        self.blocks = nn.ModuleList(
            [TRMBlock(d_model, n_heads, d_ff) for _ in range(n_layers)]
        )
        self.head = nn.Linear(d_model, vocab_size, bias=False)

    def forward(self, eq_tokens: torch.Tensor, n_recursion: int = 8):
        B, T = eq_tokens.shape
        pos = torch.arange(T, device=eq_tokens.device)
        x = self.tok_emb(eq_tokens) + self.pos_emb(pos)
        z = self.latent.expand(B, -1, -1)
        seq = torch.cat([z, x], dim=1)
        for _ in range(n_recursion):
            for block in self.blocks:
                seq = block(seq)
        return self.head(seq[:, : z.size(1) :])  # decode from latent slot


if __name__ == "__main__":
    m = TRM()
    n_params = sum(p.numel() for p in m.parameters())
    print(f"params: {n_params/1e6:.2f}M")
