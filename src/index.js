/**
 * StatStack — Cloudflare Worker
 *
 * POST /api/score   { date, sport, difficulty, score }
 *   → saves score, returns { percentile, totalPlayers }
 *
 * GET  /api/score?date=&sport=&difficulty=&score=
 *   → returns percentile for a score without saving (page reload case)
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Only handle /api/score — everything else is served as static assets
    if (!url.pathname.startsWith('/api/score')) {
      return env.ASSETS.fetch(request);
    }

    // CORS headers so the page can call the API
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Content-Type': 'application/json',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    try {
      let date, sport, difficulty, score;

      if (request.method === 'POST') {
        const body = await request.json();
        ({ date, sport, difficulty, score } = body);

        // Validate
        if (!date || !sport || !difficulty || score == null || score < 0) {
          return new Response(JSON.stringify({ error: 'Invalid payload' }), { status: 400, headers: cors });
        }

        // Insert score
        await env.DB.prepare(
          'INSERT INTO scores (date, sport, difficulty, score) VALUES (?, ?, ?, ?)'
        ).bind(date, sport, difficulty, score).run();

      } else if (request.method === 'GET') {
        date       = url.searchParams.get('date');
        sport      = url.searchParams.get('sport');
        difficulty = url.searchParams.get('difficulty');
        score      = parseInt(url.searchParams.get('score'), 10);
      } else {
        return new Response(JSON.stringify({ error: 'Method not allowed' }), { status: 405, headers: cors });
      }

      // Compute percentile: % of players whose score is WORSE (higher) than this one
      const { results } = await env.DB.prepare(`
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN score > ? THEN 1 ELSE 0 END) AS beaten
        FROM scores
        WHERE date = ? AND sport = ? AND difficulty = ?
      `).bind(score, date, sport, difficulty).all();

      const total   = results[0].total;
      const beaten  = results[0].beaten;
      const percentile = total > 1
        ? Math.round((beaten / (total - 1)) * 100)
        : null;   // only one player so far — no comparison yet

      return new Response(JSON.stringify({ percentile, totalPlayers: total }), { headers: cors });

    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), { status: 500, headers: cors });
    }
  },
};
