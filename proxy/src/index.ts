export default {
	async fetch(request: Request): Promise<Response> {
		const url = new URL(request.url);
		url.hostname = "generativelanguage.googleapis.com";
		url.port = "";
		url.protocol = "https:";

		const proxyRequest = new Request(url.toString(), {
			method: request.method,
			headers: request.headers,
			body: request.body,
		});

		return fetch(proxyRequest);
	},
};
