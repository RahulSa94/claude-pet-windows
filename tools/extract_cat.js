// Render the cat poses from the Snowwhite showcase page into art/cat/<id>.svg (static, no CSS animation).
//
//     node tools/extract_cat.js "path/to/snowwhite-cat-showcase.html"
//
// The page builds every pose with a cat(id, animated) function; this runs that function as-is.
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(process.argv[2], "utf8");
const start = html.indexOf("const poses=");
const end = html.indexOf("function save(");
if (start < 0 || end < 0) throw new Error("couldn't find poses / cat() in the page");
const { poses, cat } = new Function(html.slice(start, end) + "\nreturn { poses, cat };")();

const out = path.join(__dirname, "..", "art", "cat");
fs.mkdirSync(out, { recursive: true });
for (const [id] of poses) {
  fs.writeFileSync(path.join(out, `${id}.svg`), cat(id, false) + "\n");
  console.log("wrote", id);
}
