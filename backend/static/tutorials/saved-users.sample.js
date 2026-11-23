// Made-up records for the Users tutorials. Every id carries the reserved
// tutorial prefix ffffffff-ffff-4fff-8fff-; ids 01-08 are people, 09-14 the
// punches, work order and hand entry. The viewer is placed by id and role only.

export function sample(user) {
  const id = (n) => "ffffffff-ffff-4fff-8fff-0000002500" + String(n).padStart(2, "0");
  const stamp = "2026-11-01T12:00:00Z";
  const person = (n, username, first, last, role, extra) => ({
    id: id(n), username, first_name: first, last_name: last, full_name: `${first} ${last}`,
    role, created_at: stamp, archived_at: null, ...extra,
  });
  const tobin = person(1, "tobin.marsh", "Tobin", "Marsh", "technician");
  const users = [
    tobin,
    person(2, "wren.alder", "Wren", "Alder", "supervisor"),
    person(3, "ila.brandt", "Ila", "Brandt", "techfm_oa"),
    person(5, "pia.hollis", "Pia", "Hollis", "technician"),
    person(6, "cole.reeve", "Cole", "Reeve", "technician"),
    person(7, "dane.foley", "Dane", "Foley", "admin"),
    person(8, "mara.quill", "Mara", "Quill", "owner"),
    person(4, "odell.rusk", "Odell", "Rusk", "technician", { archived_at: "2026-11-10T12:00:00Z" }),
    { id: user.id, username: "sample.viewer", first_name: "Sample", last_name: "Viewer",
      full_name: "Sample Viewer", role: user.role, created_at: stamp, archived_at: null },
  ];
  const hubUser = (p) => ({ id: p.id, first_name: p.first_name, last_name: p.last_name, role: p.role });

  // This week's Monday, from the clock, so the dates are always current.
  const now = new Date();
  const back = (now.getDay() + 6) % 7;
  const day = (offset) => new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate() - back + offset))
    .toISOString().slice(0, 10);
  const dates = [0, 1, 2, 3, 4, 5, 6].map(day);
  const punch = (n, date, from, to, extra) => ({
    id: id(n), started_at: `${date}T${from}:00Z`, ended_at: `${date}T${to}:00Z`, start_source: "manual",
    end_source: "manual", needs_review: false, minutes: 240, carried: false, open: false,
    lunch_waived: false, crosses_midnight: false, shop: false, ...extra,
  });

  const blankAttendance = (date) => ({
    date, clocked_minutes: 0, lunch_minutes: 0, lunch_waived: false, paid_minutes: 0, tracked_minutes: 0,
    delta_minutes: 0, outside_shift_minutes: 0, adjustment_minutes: 0, needs_review: false,
    has_open: false, pending_review: false, punches: [], shop_minutes: 0,
  });
  const workday = (date, extra) => ({
    ...blankAttendance(date), clocked_minutes: 480, lunch_minutes: 30, paid_minutes: 450, ...extra,
  });
  const attendanceDays = dates.map((date, i) => {
    if (i === 0) {
      return workday(date, { tracked_minutes: 180, delta_minutes: 300, adjustment_minutes: 30,
        punches: [punch(13, date, "13:00", "21:00", { minutes: 480 })] });
    }
    if (i === 1) {
      return workday(date, { delta_minutes: 480, needs_review: true, pending_review: true,
        punches: [punch(14, date, "13:00", "21:00", { minutes: 480, needs_review: true })] });
    }
    return blankAttendance(date);
  });

  const blankPersonDay = (date) => ({
    date, clocked_minutes: 0, lunch_minutes: 0, paid_minutes: 0, charged_minutes: 0,
    adjustment_minutes: 0, uncharged_minutes: 0, completed_count: 0, needs_review: false,
    pending_review: false, has_open: false, completed: [], charged: [], adjustments: [],
    punches: [], punch_marks: [],
  });
  const monday = dates[0];
  const personDays = dates.map((date, i) => (i ? blankPersonDay(date) : {
    ...blankPersonDay(date),
    clocked_minutes: 480, lunch_minutes: 30, paid_minutes: 450, charged_minutes: 210,
    adjustment_minutes: 30, uncharged_minutes: 240, completed_count: 1,
    completed: [{ work_order_id: id(11), number: "SAMPLE-21", location: "Kitchen",
      completed_at: `${monday}T17:00:00Z`, status: "completed", archived: false }],
    charged: [{ work_order_id: id(11), number: "SAMPLE-21", minutes: 180, auto_closed: false, running: false,
      spans: [{ started_at: `${monday}T14:00:00Z`, ended_at: `${monday}T17:00:00Z` }] }],
    adjustments: [{ minutes: 30, recorded_by_name: "Wren Alder", work_order_number: "SAMPLE-21",
      labor_id: id(12), recorded_by_self: false }],
    punches: [punch(9, date, "13:00", "17:00"), punch(10, date, "17:30", "21:30")],
    punch_marks: [{ punch_id: id(9), tags: ["self"], edits: [{ by_name: "Tobin Marsh", self: true,
      field: "started_at", old: `${date}T13:15:00Z`, new: `${date}T13:00:00Z`, at: `${date}T21:45:00Z` }] }],
  }));

  return {
    "GET /tutorials/progress/users": {},
    "GET /users/": users,
    "GET /hub/attendance/week": {
      week_start: dates[0], week_end: dates[6], server_now: now.toISOString(), days: dates,
      rows: [{ user: hubUser(tobin), days: attendanceDays, total_minutes: 960, paid_minutes: 900,
        tracked_minutes: 180, delta_minutes: 780, adjustment_minutes: 30, shop_minutes: 0 }],
      totals_by_day: dates.map((date, i) => ({ date, minutes: i < 2 ? 480 : 0, paid_minutes: i < 2 ? 450 : 0 })),
      total_minutes: 960, paid_minutes: 900, tracked_minutes: 180, delta_minutes: 780,
      week_hours: 168, labor_rate: "62.50", reviewable_count: 1,
    },
    [`GET /hub/people/${tobin.id}/week`]: {
      user: hubUser(tobin), archived: false, week_start: dates[0], week_end: dates[6],
      // Sunday, so the day that opens by itself is not Monday: the script opens Monday with a tap.
      server_now: `${dates[6]}T18:00:00Z`, days: personDays,
      total_clocked_minutes: 480, total_paid_minutes: 450, total_charged_minutes: 210,
      total_adjustment_minutes: 30, total_uncharged_minutes: 240, total_completed: 1, reviewable: false,
    },
  };
}
