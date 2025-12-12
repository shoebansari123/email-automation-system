export default async function handler(req, res) {
  const { tid } = req.query;

  console.log("Pixel hit with TID:", tid);

  const pixel = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6X6ZQAAAABJRU5ErkJggg==",
    "base64"
  );

  if (tid) {
    const trackingEndpoint = "https://tawanda-workaday-biotechnologically.ngrok-free.dev/update_open?tid=" + encodeURIComponent(tid);

    console.log("Calling tracking endpoint:", trackingEndpoint);

    try {
      const response = await fetch(trackingEndpoint, {
        headers: { "ngrok-skip-browser-warning": "true" }
      });
      console.log("Fetch response status:", response.status);
    } catch (err) {
      console.log("Fetch error:", err.message);
    }
  }

  res.setHeader("Content-Type", "image/png");
  res.setHeader("Content-Length", pixel.length);
  res.status(200).send(pixel);
}
