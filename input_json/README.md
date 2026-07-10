# input_json

Put your **JSON metadata file(s)** here.

- To apply the **same** metadata to every PDF, put a **single** `.json` file
  in this folder.
- To give each PDF its **own** metadata, name the JSON to match the PDF, e.g.
  `report.pdf` uses `report.json`.

Each JSON is a flat object of `"Field": "Value"` pairs, for example:

```json
{
  "Title": "Quarterly Business Review",
  "Author": "Shivaji Chaprana",
  "copyright": "© 2026 Shivaji Chaprana",
  "language": "en"
}
```
