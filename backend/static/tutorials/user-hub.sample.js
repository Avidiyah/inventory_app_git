// Made-up records for the User Hub tutorials. Every id carries the reserved
// tutorial prefix ffffffff-ffff-4fff-8fff-, so a stray write cannot touch a
// real record; only the viewer's own id is real. Id blocks: 0000000000NN
// (Home, My Work Orders), 0000002100NN (Dashboard, Timesheets), 0000004100NN
// (Leaderboards, Report). Dates come from today, never fixed.

export function sample(user) {
  const P = "ffffffff-ffff-4fff-8fff-";
  const id = (tail) => P + tail;
  const viewerName = user.full_name || "You";
  const now = new Date();
  const ago = (min) => new Date(now.getTime() - min * 60000).toISOString();
  const pad = (n) => String(n).padStart(2, "0");
  const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7));
  // A date `offset` days from this week's Monday (negative = earlier).
  const dayAt = (offset) => ymd(new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + offset));
  const person = (tail, first, last, role = "technician") => ({ id: id(tail), first_name: first, last_name: last, role });

  const viewer = { id: user.id, first_name: user.first_name ?? null, last_name: user.last_name ?? null, role: user.role };
  const tobin = person("000000210002", "Tobin", "Marsh");
  const ila = person("000000210003", "Ila", "Brandt");
  const odell = person("000000210004", "Odell", "Rusk");
  const wren = person("000000210005", "Wren", "Alder");

  // --- GET /hub, GET /attendance/me (Home, Dashboard) -------------------------
  const hub = {
    user: viewer,
    server_now: now.toISOString(),
    day: ymd(now),
    clock: {
      running_session: null, closed_minutes_today: 60, running_minutes_today: 0,
      adjustment_minutes_today: 0, adjustments: [], total_minutes_today: 60,
    },
    timeline: [{
      work_order_id: id("000000000052"), number: "SAMPLE-52", started_at: ago(125), ended_at: ago(65),
      auto_closed: false, minutes: 60,
    }],
    mine_total: 2,
    counts: { assigned: 2, in_progress: 1, ready_to_complete: 1 },
    priority: { assigned: 1, unassigned: null },
    // The Owner cannot run a job clock, so nothing is offered to start.
    startable: user.role === "owner" ? [] : [{
      work_order_id: id("000000000051"), number: "SAMPLE-51", status: "in_progress",
      community: "Sample Village", building_number: "4", unit_number: "12", location: "Kitchen",
    }],
    tools_out: [{
      tool_id: id("000000210001"), name: "Cordless drill", barcode: "TOOL-SAMPLE-1", quantity: "1", since: ago(2 * 24 * 60),
    }],
    stocked_requests: [],
  };
  const attendanceMe = {
    server_now: now.toISOString(),
    day: ymd(now),
    open_punch: null,
    clocked_minutes_today: 60,
    week_punches: [{ id: id("000000000053"), started_at: ago(185), ended_at: ago(125), needs_review: false, tags: [], shop: false }],
  };

  // --- My Work Orders (the shared list module) -----------------------------
  const card = (tail, number, status, extra) => ({
    id: id(tail), number, community: "Sample Village", building_number: "4", unit_number: "12",
    description: "Kitchen sink is leaking under the cabinet", priority: "Normal", status,
    entry_mode: "dispense", created_by_id: null, assigned_to_id: null, assigned_to_name: null,
    assigned_to_ids: [user.id], assigned_to_names: [viewerName], item_count: 0, location: "Kitchen",
    output_to: null, vendor_assignee: null, service_type: "Plumbing", schedule_date: ymd(now),
    supervisor_id: null, supervisor_name: null, legacy: false, ...extra,
  });
  const workOrders = [
    card("000000000051", "SAMPLE-51", "in_progress"),
    card("000000000052", "SAMPLE-52", "assigned", { description: "Hallway light is out", service_type: "Electrical", location: "Hallway" }),
  ];

  // --- Dashboard: crew and company ------------------------------------------
  const crew = {
    server_now: now.toISOString(),
    led: { total: 3, in_progress: 1, ready_to_complete: 1 },
    priority: { assigned: 2, unassigned: 1 },
    crew_on_clock: 1,
    crew_total: 2,
    crew_minutes_today: 150,
    technicians: [
      {
        user: tobin,
        running_session: { work_order_id: id("000000210006"), number: "SAMPLE-51", started_at: ago(90), day_counting_from: ago(90) },
        minutes_today: 90, assigned: 2, in_progress: 1, ready_to_complete: 0, last_worked: ago(90), flags: [],
      },
      {
        user: ila, running_session: null, minutes_today: 60, assigned: 1, in_progress: 0, ready_to_complete: 1,
        last_worked: ago(200), flags: ["assigned_idle"],
      },
    ],
    attention: [{ kind: "assigned_idle", subject: "Ila Brandt", detail: "assigned work, no time yet today" }],
  };
  const admin = {
    server_now: now.toISOString(),
    supervisor_minutes_today: 120,
    technician_minutes_today: 360,
    pipeline: { created: 3, assigned: 5, in_progress: 4, ready_to_complete: 1, completed: 6, review: 2 },
    priority: { assigned: 2, unassigned: 1 },
    on_the_clock: [{
      technician_name: "Tobin Marsh", work_order_number: "SAMPLE-51", community: "Sample Village",
      started_at: ago(90), elapsed_minutes: 90, flag: null,
    }],
    exceptions: { inventory_recounts: 2, missing_item_price: 1, catalogue_requests: 0, admin_review_queue: 1, stale_work_orders: 3 },
    billing: {
      materials_total: "420.50", labor_total: "1250.00", total: "1670.50", avg_days_to_complete: 2.4,
      completed_per_day: [1, 2, 0, 3, 1, 0, 0], legacy_live_count: null,
    },
  };

  // --- Timesheets: roster, week and Monday's day page ------------------------
  const live = {
    server_now: now.toISOString(),
    idle_red_minutes: 10,
    on_shift: [
      { user: tobin, state: "green", punch_started_at: ago(180), idle_since: null, idle_minutes: 0, charging_since: ago(90), work_order_number: "SAMPLE-51" },
      { user: ila, state: "yellow", punch_started_at: ago(150), idle_since: ago(4), idle_minutes: 4, charging_since: null, work_order_number: null },
      { user: odell, state: "shop", punch_started_at: ago(60), idle_since: null, idle_minutes: 0, charging_since: null, work_order_number: null },
    ],
    absent: [{ user: wren, state: "gray", punch_started_at: null, idle_since: null, idle_minutes: 0, charging_since: null, work_order_number: null }],
    on_shift_count: 3, charging_count: 1, idle_count: 1, shop_count: 1,
  };
  const mon = dayAt(0);
  const days = [0, 1, 2, 3, 4, 5, 6].map(dayAt);
  const blankDay = (date) => ({
    date, clocked_minutes: 0, lunch_minutes: 0, lunch_waived: false, paid_minutes: 0, tracked_minutes: 0,
    delta_minutes: 0, outside_shift_minutes: 0, adjustment_minutes: 0, needs_review: false, has_open: false,
    pending_review: false, punches: [], shop_minutes: 0,
  });
  const punch = (tail, started, ended, extra) => ({
    id: id(tail), started_at: `${mon}T${started}:00Z`, ended_at: ended ? `${mon}T${ended}:00Z` : null,
    start_source: "manual", end_source: ended ? "manual" : null, needs_review: false, minutes: 0,
    carried: false, open: !ended, lunch_waived: false, crosses_midnight: false, shop: false, ...extra,
  });
  const weekRow = (who, mondayDay, totals) => ({
    user: who, days: days.map((d) => (d === mon ? mondayDay : blankDay(d))), total_minutes: totals.clocked,
    paid_minutes: totals.paid, tracked_minutes: totals.tracked, delta_minutes: totals.clocked - totals.tracked,
    adjustment_minutes: 0, shop_minutes: 0,
  });
  const week = {
    week_start: mon,
    week_end: dayAt(6),
    server_now: now.toISOString(),
    days,
    rows: [
      // A normal day with the automatic lunch taken off.
      weekRow(tobin, {
        ...blankDay(mon), clocked_minutes: 510, lunch_minutes: 30, paid_minutes: 480, tracked_minutes: 420, delta_minutes: 60,
        punches: [punch("000000210011", "12:00", "20:30", { minutes: 510 })],
      }, { clocked: 510, paid: 480, tracked: 420 }),
      // Still on shift: an open punch.
      weekRow(ila, {
        ...blankDay(mon), clocked_minutes: 180, paid_minutes: 180, tracked_minutes: 120, delta_minutes: 60, has_open: true,
        punches: [punch("000000210012", "13:00", null, { minutes: 180 })],
      }, { clocked: 180, paid: 180, tracked: 120 }),
      // Closed by the midnight sweep, so it waits for review and is left out of totals.
      weekRow(odell, {
        ...blankDay(mon), clocked_minutes: 690, lunch_minutes: 30, paid_minutes: 660, tracked_minutes: 600, delta_minutes: 90,
        needs_review: true, pending_review: true,
        punches: [punch("000000210013", "12:00", "23:30", { minutes: 690, end_source: "auto_clock_out", needs_review: true })],
      }, { clocked: 690, paid: 660, tracked: 600 }),
    ],
    totals_by_day: days.map((date) => ({ date, minutes: date === mon ? 1380 : 0, paid_minutes: date === mon ? 660 : 0 })),
    total_minutes: 1380,
    paid_minutes: 660,
    tracked_minutes: 1140,
    delta_minutes: 240,
    week_hours: 168,
    labor_rate: "62.50",
    reviewable_count: 1,
  };

  // --- Leaderboards -----------------------------------------------------------
  const scaled = (billed, efficiency, accuracy, clean_days) => ({ billed, efficiency, accuracy, clean_days });
  const perfRow = (tail, first, last, extra) => ({
    user: person(tail, first, last), rank: null, below_floor: false, score: 0, billed_dollars: "0.00",
    efficiency_pct: 0, accuracy_pct: 0, counted_days: 0, active_days: 0, clocked_minutes: 0,
    scaled: scaled(0, 0, 0, 0), day_reasons: [], excluded_orders: [], ...extra,
  });
  const performance = {
    window: "week",
    start: mon,
    end: dayAt(6),
    to_date: true,
    server_now: now.toISOString(),
    weights: { billed: 40, efficiency: 25, accuracy: 20, clean_days: 15 },
    floor_minutes: 960,
    rows: [
      perfRow("000000410001", "Wren", "Alder", {
        rank: 1, score: 96, billed_dollars: "1180.00", efficiency_pct: 94, accuracy_pct: 91, counted_days: 5,
        active_days: 5, clocked_minutes: 2400, scaled: scaled(100, 94, 91, 100),
      }),
      perfRow("000000410002", "Tobin", "Marsh", {
        rank: 2, score: 88, billed_dollars: "980.00", efficiency_pct: 90, accuracy_pct: 85, counted_days: 4,
        active_days: 5, clocked_minutes: 2300, scaled: scaled(83, 96, 93, 80),
        day_reasons: [{ code: "punch_estimated", label: "forgotten clock-out", days: 1 }],
      }),
      perfRow("000000410003", "Ila", "Brandt", {
        rank: 3, score: 74, billed_dollars: "760.00", efficiency_pct: 81, accuracy_pct: 78, counted_days: 4,
        active_days: 4, clocked_minutes: 1900, scaled: scaled(64, 86, 86, 100),
      }),
      perfRow("000000410004", "Odell", "Rusk", {
        rank: 4, score: 61, billed_dollars: "540.00", efficiency_pct: 70, accuracy_pct: 72, counted_days: 3,
        active_days: 4, clocked_minutes: 1500, scaled: scaled(46, 75, 79, 75),
      }),
      perfRow("000000410005", "Sable", "Quint", {
        below_floor: true, score: 40, billed_dollars: "120.00", efficiency_pct: 75, accuracy_pct: 75, counted_days: 1,
        active_days: 1, clocked_minutes: 300, scaled: scaled(10, 80, 82, 100),
        excluded_orders: [{ number: "SAMPLE-71", reason: "session_auto_closed", label: "job clock auto-closed" }],
      }),
      perfRow("000000410006", "Marlo", "Fenn", {
        below_floor: true, score: 22, billed_dollars: "60.00", efficiency_pct: 60, accuracy_pct: 70, counted_days: 1,
        active_days: 2, clocked_minutes: 420, scaled: scaled(5, 64, 75, 50),
      }),
    ],
  };

  // --- Graphs -----------------------------------------------------------------
  const cells = [
    ["scholars", "Plumbing", "Normal", "assigned", 3], ["scholars", "Plumbing", "Normal", "in_progress", 2],
    ["scholars", "Plumbing", "Urgent", "created", 1], ["scholars", "Electrical", "Normal", "assigned", 2],
    ["scholars", "Electrical", "Normal", "ready_to_complete", 1], ["scholars", "HVAC", "High", "in_progress", 1],
    ["scholars", "HVAC", "Normal", "completed", 2],
    ["centennial", "Plumbing", "Normal", "created", 2], ["centennial", "Electrical", "Urgent", "in_progress", 2],
    ["centennial", "Carpentry", "Normal", "assigned", 1], ["centennial", "HVAC", "Normal", "on_hold", 1],
    ["commons", "Plumbing", "Normal", "assigned", 2], ["commons", "Electrical", "Normal", "in_progress", 1],
    ["commons", "Carpentry", "High", "created", 1], ["commons", "Electrical", "Normal", "completed", 2],
    ["young_hall", "HVAC", "Normal", "assigned", 2], ["young_hall", "Plumbing", "Urgent", "in_progress", 1],
    ["young_hall", "Electrical", "Normal", "review", 1], ["young_hall", "Carpentry", "Normal", "ready_to_complete", 1],
    ["academics", "Electrical", "Normal", "assigned", 1], ["academics", "Plumbing", null, "created", 1],
    ["academics", "HVAC", "Normal", "in_progress", 2], ["academics", "Carpentry", "Normal", "assigned", 1],
    [["scholars", "commons"], "Plumbing", "Normal", "assigned", 1],
    [["centennial", "academics"], "Electrical", "Urgent", "created", 1],
  ].map(([c, service_type, priority, status, count]) => ({
    communities: Array.isArray(c) ? c : [c], service_type, priority, status, count,
  }));
  // Twelve Mondays, the last one still in progress. Week 5 has few samples and
  // week 7 closed nothing that was scheduled.
  const median = [4.5, 5.0, 4.2, 5.8, 6.1, 5.5, 4.9, 5.2, 6.0, 5.7, 5.1, 4.8];
  const closedMedian = [2.1, 2.5, 1.9, 2.8, 3.4, 2.2, 2.6, 2.0, 2.4, 3.1, 2.3, 1.8];
  const scheduled = [8, 9, 7, 8, 3, 8, 0, 7, 9, 10, 8, 4];
  const onTime = [6, 7, 5, 7, 2, 6, 0, 6, 8, 9, 6, 3];
  const unscheduled = [1, 0, 2, 1, 0, 1, 5, 0, 1, 0, 2, 1];
  const buckets = median.map((m, i) => {
    const back = 11 - i;
    return {
      start: dayAt(-7 * back), end: dayAt(-7 * back + 6), partial: i === 11,
      circulating_median_age_days: m, circulating_p90_age_days: Math.round(m * 18) / 10, circulating_count: 14 + i,
      closed_median_days: closedMedian[i], closed_p90_days: Math.round(closedMedian[i] * 17) / 10,
      closed_count: scheduled[i] + unscheduled[i],
      on_time_pct: scheduled[i] ? Math.round((onTime[i] * 1000) / scheduled[i]) / 10 : null,
      on_time_count: onTime[i], scheduled_closed_count: scheduled[i], unscheduled_closed_count: unscheduled[i],
    };
  });
  const graphs = {
    generated_at: now.toISOString(),
    weeks: 12,
    statuses: [
      { key: "created", label: "Created" }, { key: "assigned", label: "Assigned" },
      { key: "in_progress", label: "In-Progress" }, { key: "on_hold", label: "On-Hold" },
      { key: "ready_to_complete", label: "Ready to Complete" }, { key: "completed", label: "Completed" },
      { key: "review", label: "Review" },
    ],
    communities: [
      { key: "scholars", label: "Scholars" }, { key: "centennial", label: "Centennial" },
      { key: "commons", label: "Commons" }, { key: "young_hall", label: "Young Hall" },
      { key: "academics", label: "Academics" },
    ],
    cells,
    duration: { range: { start: buckets[0].start, end: buckets[11].end }, buckets },
  };

  // --- Report: last week, a finished (frozen) one -----------------------------
  const closedRow = (tail, number, service, community, offset) => ({
    work_order_id: id(tail), number, assigned_to: "Sample Crew", location: `${community === "scholars" ? "Scholars" : "Commons"} 12-30${offset}`,
    service_type: service, service_type_label: service, community, schedule_date: dayAt(-7 + offset).replace(/^(\d+)-(\d+)-(\d+)$/, "$2/$3/$1"),
    priority: "Normal", archived_at: `${dayAt(-7 + offset)}T18:30:00Z`,
  });
  const report = {
    week_start: dayAt(-7),
    week_end: dayAt(-1),
    status: "completed",
    generated_at: `${dayAt(0)}T05:00:00Z`,
    frozen_at: `${dayAt(0)}T05:00:00Z`,
    count: 7,
    rows: [
      closedRow("000000410011", "S-101", "Electrical", "scholars", 0), closedRow("000000410012", "S-102", "Electrical", "commons", 1),
      closedRow("000000410013", "S-103", "HVAC", "scholars", 2), closedRow("000000410014", "S-104", "HVAC", "commons", 3),
      closedRow("000000410015", "S-105", "Plumbing", "scholars", 3), closedRow("000000410016", "S-106", "Plumbing", "commons", 4),
      closedRow("000000410017", "S-107", "Plumbing", "scholars", 5),
    ],
    new_work_order_count: 4,
    new_work_order_rows: [
      { ...closedRow("000000410021", "S-201", "Plumbing", "scholars", 1), archived_at: null },
      { ...closedRow("000000410022", "S-202", "Electrical", "commons", 2), archived_at: null },
      { ...closedRow("000000410023", "S-203", "HVAC", "scholars", 3), archived_at: null },
      { ...closedRow("000000410024", "S-204", "Plumbing", "commons", 4), archived_at: null },
    ],
  };

  return {
    "GET /hub": hub,
    "GET /attendance/me": attendanceMe,
    "GET /work-orders/": workOrders,
    "GET /hub/crew": crew,
    "GET /hub/admin": admin,
    "GET /hub/attendance/live": live,
    "GET /hub/attendance/week": week,
    "GET /hub/performance": performance,
    "GET /hub/graphs": graphs,
    "GET /hub/report": report,
  };
}
