export default async function handler(req, res) {
  const { tid } = req.query;

  // 1x1 transparent PNG
  const pixel = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6X6ZQAAAABJRU5ErkJggg==",
    "base64"
  );

  // Call your tracking endpoint (ngrok URL)
  if (tid) {
    // IMPORTANT: replace with your real ngrok URL
    const trackingEndpoint = "https://tawanda-workaday-biotechnologically.ngrok-free.dev/update_open?tid=" + encodeURIComponent(tid);


    fetch(trackingEndpoint).catch(() => { /* ignore errors */ });
  }

  res.setHeader("Content-Type", "image/png");
  res.setHeader("Content-Length", pixel.length);
  res.status(200).send(pixel);
}
