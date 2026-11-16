import { Activity, BookOpen, Library, Workflow } from "lucide-react";

/** The four places a user can be. Keys are stable strings used by the store. */
export const ROUTES = [
  { key: "research", label: "Research", icon: BookOpen, short: "Research" },
  { key: "trace", label: "Execution trace", icon: Activity, short: "Trace" },
  { key: "lab", label: "FODS Lab", icon: Workflow, short: "Lab" },
  { key: "library", label: "Library", icon: Library, short: "Library" },
];

export function routeByKey(key) {
  return ROUTES.find((route) => route.key === key) || ROUTES[0];
}
