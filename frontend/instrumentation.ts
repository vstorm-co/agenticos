import { registerOTel } from "@vercel/otel";

/**
 * Register the OpenTelemetry SDK for the server half of this app.
 *
 * Whether anything *receives* the spans is the deployment's call, not this
 * file's: off Vercel, `@vercel/otel` attaches an exporter only when
 * `OTEL_EXPORTER_OTLP_ENDPOINT` is set, so an installation that has not set it
 * builds spans and drops them. That is the default, and it is deliberate - the
 * backend's Logfire token is required configuration because the backend is where
 * a run's cost and refusals are recorded; a route handler proxying a request is
 * not worth making an operator configure a collector to boot. `frontend/README.md`
 * has the pair of variables, and `docker-compose-prod.frontend.yml` passes them
 * through.
 */
export function register() {
  registerOTel({
    serviceName: "agenticos-frontend",
  });
}
