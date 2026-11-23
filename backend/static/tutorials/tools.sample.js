// Made-up records for the Tools tutorials. Every id carries the reserved
// tutorial prefix, except the viewer's own. Dates are relative to now.

export function sample(user) {
  const P = "ffffffff-ffff-4fff-8fff-";
  const day = 86400000;
  const ago = (days) => new Date(Date.now() - days * day).toISOString();
  const viewerName = user.full_name || "You";
  const person = (id, first, last, role) => ({
    id: P + id, username: `${first}.${last}`.toLowerCase(), first_name: first, last_name: last,
    full_name: `${first} ${last}`, role, created_at: ago(60), archived_at: null,
  });
  const pat = person("000000000041", "Pat", "Sample", "technician");
  const alex = person("000000000021", "Alex", "Rivera", "technician");
  const jordan = person("000000000022", "Jordan", "Lee", "supervisor");
  const casey = person("000000000023", "Casey", "Moore", "technician");
  const tool = (id, barcode, name, quantity, custody) => ({
    id: P + id, barcode, name, quantity, created_at: ago(90), custody,
  });
  const held = (who, quantity) => ({ user_id: who.id, user_name: who.full_name, quantity });
  return {
    "GET /tools/": [
      tool("000000000031", "TL-0031", "Impact driver", "0",
        [{ user_id: user.id, user_name: viewerName, quantity: "1" }]),
      tool("000000000032", "TL-0032", "Extension cord", "3", [held(pat, "2")]),
      tool("000000000071", "TL-0071", "Cordless drill", "2", []),
      tool("000000000072", "TL-0072", "Pipe wrench", "0", [held(jordan, "1")]),
      tool("000000000073", "TL-0073", "Zip ties, bag of 100", "40", []),
    ],
    "GET /users/": [
      { id: user.id, username: user.username, first_name: user.first_name, last_name: user.last_name,
        full_name: viewerName, role: user.role, created_at: user.created_at || ago(120), archived_at: null },
      pat, alex, jordan, casey,
    ],
  };
}
