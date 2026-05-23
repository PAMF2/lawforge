# Kaggle vLLM proxy

Same idea as `notebooks/colab_vllm_proxy.ipynb` but for Kaggle (30h/week guaranteed T4).

## Usage

```bash
# from repo root
cd kaggle/
# edit lawforge_vllm_proxy.ipynb (insert your HF token in cell 2)
kaggle kernels push -p .
```

On Kaggle web UI:

1. Right pane → Accelerator → `GPU T4 x1`
2. Internet → On
3. Run All

Last cell prints the cloudflared URL. Also written to `/kaggle/working/url.txt`.

Local pickup:

```bash
kaggle kernels output pedroafonso2/lawforge-vllm-proxy -p /tmp/kag
cat /tmp/kag/url.txt
```

## Files

- `kernel-metadata.json` — Kaggle kernel config (tracked)
- `lawforge_vllm_proxy.ipynb` — notebook with hardcoded HF token (gitignored — local only)

## Generating notebook from scratch

If you cloned this repo fresh and need to rebuild the notebook, use
`notebooks/colab_vllm_proxy.ipynb` as a template — same vLLM/cloudflared
sequence, just swap Colab Secrets reading for hardcoded token.
