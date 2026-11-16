// C# File-based app: the expected input is a base64+Brotli blob embedded in chal.cs.
// decode: base64 -> Brotli-decompress -> flag.
const z=require("zlib");
const b=Buffer.from("GzMA+MVtbG/XtFYgGNGLSpSiwoAdaiYvxraqBw==","base64");
console.log(z.brotliDecompressSync(b).toString());
