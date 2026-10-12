import { onRequestGet as __api_geocode_js_onRequestGet } from "C:\\bh\\wt-wo40a\\web\\functions\\api\\geocode.js"
import { onRequestGet as __api_whereami_js_onRequestGet } from "C:\\bh\\wt-wo40a\\web\\functions\\api\\whereami.js"

export const routes = [
    {
      routePath: "/api/geocode",
      mountPath: "/api",
      method: "GET",
      middlewares: [],
      modules: [__api_geocode_js_onRequestGet],
    },
  {
      routePath: "/api/whereami",
      mountPath: "/api",
      method: "GET",
      middlewares: [],
      modules: [__api_whereami_js_onRequestGet],
    },
  ]