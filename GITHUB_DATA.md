# Moving the BTC prediction data through GitHub

This directory is approximately 226 MB. Binary market archives and generated
CSV/NPZ datasets are configured for Git LFS in `.gitattributes`; source code,
reports, and documentation remain ordinary Git files.

## First upload

Git LFS must be installed before the first commit:

```sh
git lfs install
git add .gitattributes .gitignore
git add .
git commit -m "Add BTC prediction training data and models"
git push -u origin main
```

The GitHub repository should be private unless the data and research outputs are
intended to be public. The source Binance and Kalshi datasets are public, but
GitHub visibility also exposes the derived models and research.

## Download on another machine

Install Git and Git LFS, then:

```sh
git lfs install
git clone https://github.com/Shad0wSeven/btpred-data.git
cd btpred-data
git lfs pull
```

Confirm that LFS objects were downloaded:

```sh
git lfs ls-files
du -sh .
```

If a ZIP file contains a short text pointer beginning with
`version https://git-lfs.github.com/spec/v1`, run `git lfs pull`.

## Updating the dataset

After adding new archives or generated CSV files:

```sh
git add .
git commit -m "Update BTC training data"
git push
```

GitHub LFS usage is metered by stored bytes and downloaded bandwidth. Cloning
the dataset to many machines consumes LFS bandwidth each time.
