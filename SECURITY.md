# Security Policy

## Reporting a vulnerability

If you find a security issue in pdfmeta, please report it privately using
GitHub's [private vulnerability reporting](https://github.com/shivajichaprana/pdfmeta/security/advisories/new)
rather than opening a public issue. I'll aim to respond within a few days.

## Scope notes

- `pdfmeta gui` starts a local web server bound to `127.0.0.1` only; it is not
  intended to be exposed to a network. Do not run it behind a public interface.
- pdfmeta edits metadata in place using pikepdf and never uploads your files
  anywhere.

## Supported versions

The latest released version receives fixes. pdfmeta targets Python 3.9+.
