// Made-up answer for the Integrations tutorials. The page fires one GET on load:
// the caller's NetFacilities cloud-session capability. No ids are involved.

export function sample() {
  return {
    "GET /integrations/netfacilities/cloud/session": {
      available: true,
      message: "Log in to NetFacilities from any device.",
      status: null,
      has_saved_session: true,
    },
  };
}
