// ==UserScript==
// @name         bnetswitch LFG bridge
// @namespace    https://github.com/xyzyx/neo-mittens
// @version      0.9.9
// @description  Taps Discord's WebSocket gateway directly to forward Overwatch LFG embeds + voice-state updates to bnetswitch's local HTTP server. Push-based, complete coverage, no DOM polling.
// @match        https://discord.com/*
// @match        https://canary.discord.com/*
// @match        https://ptb.discord.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_log
// @grant        GM_addElement
// @grant        unsafeWindow
// @run-at       document-start
// @connect      127.0.0.1
// @connect      localhost
// @require      https://cdn.jsdelivr.net/npm/pako@2.1.0/dist/pako.min.js
// @updateURL    http://127.0.0.1:7172/bnetswitch-lfg.user.js
// @downloadURL  http://127.0.0.1:7172/bnetswitch-lfg.user.js
// ==/UserScript==
//
// =============================================================================
// ARCHITECTURE (v0.8.2)
// =============================================================================
//
// Discord's web client maintains a WebSocket gateway connection to
// gateway.discord.gg (and regional shards like gateway-us-east1-c.discord.gg)
// using compress=zlib-stream encoding. ALL state changes (messages, voice
// updates, channel edits, member joins, etc.) flow through that WebSocket
// as zlib-wrapped (78 da ...) deflate-compressed JSON. The encoder uses
// Z_SYNC_FLUSH between messages: each WS frame ends with bytes 00 00 ff ff.
//
// PIPELINE (page world):
//   1. At document-start we patch `window.WebSocket` constructor (PatchedWS)
//      AND `WebSocket.prototype.addEventListener`+`onmessage`. Both patches
//      are necessary because Discord's bundle may cache the original
//      WebSocket constructor before our @run-at document-start userscript
//      runs (race in Chromium MV3 + Tampermonkey).
//   2. Our PatchedWS does NOT modify the URL. Tried that in v0.8.0 -- it
//      breaks Discord because its bundle has its decompressor (eu.feed)
//      wired up to expect binary frames based on its own config, not the
//      URL. Stripping compress= triggers "Expected array buffer, but got
//      string" inside Discord, freezing the client on the splash screen.
//      So we let Discord see exactly what it expects, AND we tap the
//      compressed stream ourselves.
//   3. THE FIRST WS we observe is mid-stream -- our patches were a hair
//      too late. Its first bytes (e.g. dc bd ...) are mid-deflate-block,
//      not the zlib magic 78 da. Without the prior LZ77 dictionary we
//      can't decode it. We force-close that first WS once with code 4000.
//      Discord auto-reconnects (often to a regional shard) THROUGH our
//      PatchedWS this time, and our prototype patch attaches to onmessage
//      from the very first frame -- which begins with the zlib header
//      78 da, decoding cleanly thereafter.
//   4. Binary frames are forwarded via CustomEvent on `document` to the
//      userscript world (window.postMessage does NOT cross worlds in MV3
//      + TM, but DOM events do).
//
// PIPELINE (userscript world):
//   - DecompressionStream('deflate') (zlib-wrapped) maintains streaming
//     state per WS id. Each frame ends with the sync-flush marker
//     00 00 ff ff; after the marker we read the accumulated text as one
//     JSON object and dispatch to handleGatewayMessage(). Falls back to
//     'deflate-raw' on the first decompression error in case some Discord
//     deployments use raw deflate.
//   - Updates GW.channels + GW.voiceStates + GW.userVoiceChannel from
//     READY / GUILD_CREATE / VOICE_STATE_UPDATE.
//   - Filters MESSAGE_CREATE/UPDATE for LFG Tool embeds in
//     WATCHED_CHANNEL_IDS, parses author + description + voice channel
//     ID + URL, POSTs to bnetswitch.
//   - HTTP-polls /actions for join/nickname commands; executes via DOM
//     walk for nickname-change (no gateway equivalent) and pushState for
//     VC join.
//
// =============================================================================

/* eslint-env browser, greasemonkey */
/* global GM_xmlhttpRequest, GM_setValue, GM_getValue, GM_log, GM_addElement, unsafeWindow */

(function () {
  "use strict";

  // ============================================================================
  // Config
  // ============================================================================
  const BNETSWITCH_HOST = "http://127.0.0.1:7172";
  const BNETSWITCH_TOKEN = "bnetswitch-lfg-localhost-only-do-not-expose";
  const LFG_BOT_USERNAME = "LFG Tool";
  const ACTION_POLL_INTERVAL_MS = 2000;
  const SESSION_REGISTER_INTERVAL_MS = 20000; // re-register every 20s

  // Self-reported version. Match the @version metadata at the top of
  // this file. Exposed via bnetswitchLfgDiagnose so we can confirm
  // which build is actually loaded after a TM update or loader reload
  // (the @version banner is only visible in TM's UI).
  const USERSCRIPT_VERSION = "0.9.9";

  // Per-userscript-instance ID for multi-browser leader election.
  // bnetswitch elects the most-recently-registered tab as primary
  // and only delivers /actions to that one. Other tabs/browsers stay
  // active for ingestion + backfill but don't execute joins.
  const SESSION_ID = (() => {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return "sess-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
  })();

  // Channel IDs to watch for LFG messages. Empty = watch every channel
  // (still filtered by author == LFG_BOT_USERNAME).
  const WATCHED_CHANNEL_IDS = [
    "182420486582435840", // #lfg-pc-na-ranked
  ];

  // ============================================================================
  // Logging
  // ============================================================================
  const log = (...args) => GM_log("[bnetswitch-lfg] " + args.map(String).join(" "));
  const warn = (...args) => log("WARN:", ...args);
  const debug = (...args) => {
    if (GM_getValue("debug", false)) log("DEBUG:", ...args);
  };

  const stats = {
    gateway_connections: 0,
    gateway_events: 0,
    lfg_posts_observed: 0,
    lfg_posts_forwarded: 0,
    voice_state_updates: 0,
    posts_attempted: 0,
    posts_succeeded: 0,
    posts_failed: 0,
  };

  // ============================================================================
  // Gateway state cache
  //
  // Updated by handleGatewayMessage() in response to Discord events.
  // Read by postLfgMessage() to enrich each LFG embed with VC info.
  // ============================================================================
  const GW = {
    // channel_id -> { name, type, user_limit, guild_id, parent_id }
    channels: new Map(),
    // channel_id -> Set<user_id>  (live voice membership)
    voiceStates: new Map(),
    // user_id -> channel_id  (reverse: which VC is each user in?)
    userVoiceChannel: new Map(),
    // guild_id -> { name }
    guilds: new Map(),
    // Our own user id (from READY)
    meId: null,
    ready: false,
  };

  // -------------------------------------------------------------------------
  // In-voice flag default-false safety timeout
  //
  // The loader uses unsafeWindow.__bnet_self_in_voice to gate
  // auto-reload. We set it true on VSU-for-self with channel_id, and
  // false on VSU-for-self with null channel_id OR at end of READY
  // when no self VSU was seen.
  //
  // BUT: when Discord auto-reconnects after our forced 4000-close
  // (needed to capture deflate-from-start), the NEW connection sends
  // RESUMED, not READY. The READY code path that flips undefined -> false
  // never runs. The flag stays undefined, and the loader's isInVoice()
  // defaults undefined to TRUE for safety -- meaning auto-reload is
  // permanently blocked even when the user isn't in voice at all.
  //
  // Fix: after the gateway has been alive for 12s and no VSU for
  // self has arrived, we're confidently NOT in voice (joining voice
  // generates a self VSU within ~1s; 12s is enough margin for slow
  // boot races). Flip undefined -> false then.
  setTimeout(() => {
    try {
      if (unsafeWindow.__bnet_self_in_voice === undefined) {
        unsafeWindow.__bnet_self_in_voice = false;
        console.log(
          "[bnetswitch-lfg] in-voice flag defaulted to false " +
          "(no self VSU after 12s; likely RESUME without READY)"
        );
      }
    } catch (_) {}
  }, 12000);

  // ============================================================================
  // HTTP helper (talks to bnetswitch on localhost)
  // ============================================================================
  function bnetRequest(method, path, body = null) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method,
        url: BNETSWITCH_HOST + path,
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + BNETSWITCH_TOKEN,
          // Session ID for leader election. bnetswitch tracks the
          // most recently active session and only delivers /actions
          // to that one, so multi-browser doesn't race.
          "X-Bnet-Session": SESSION_ID,
        },
        data: body ? JSON.stringify(body) : null,
        onload: (resp) => {
          if (resp.status >= 200 && resp.status < 300) {
            try {
              resolve(resp.responseText ? JSON.parse(resp.responseText) : null);
            } catch (e) {
              resolve(resp.responseText);
            }
          } else {
            reject(new Error(`HTTP ${resp.status}: ${resp.responseText}`));
          }
        },
        onerror: (err) => reject(new Error(`network error: ${err && err.error}`)),
        ontimeout: () => reject(new Error("timeout")),
        timeout: 5000,
      });
    });
  }

  // ============================================================================
  // Diagnostic function exposed on window for the user to call from console
  // ============================================================================
  (typeof unsafeWindow !== "undefined" ? unsafeWindow : window).bnetswitchLfgDiagnose =
    function () {
      console.log("=== bnetswitch-lfg gateway-tap diagnostic ===");
      console.log("userscript version:", USERSCRIPT_VERSION);
      console.log("stats:", stats);
      console.log("gateway ready:", GW.ready);
      console.log("known guilds:", GW.guilds.size);
      console.log("known channels:", GW.channels.size);
      console.log("voice states tracked:", GW.voiceStates.size, "channels with users");
      let totalUsersInVoice = 0;
      for (const users of GW.voiceStates.values()) totalUsersInVoice += users.size;
      console.log("total users currently in voice:", totalUsersInVoice);
      console.log("watched channel IDs:", WATCHED_CHANNEL_IDS);
      console.log("subscribed guilds (op 14 sent):", subscribedGuilds.size,
                  Array.from(subscribedGuilds));
      console.log("tracked LFG VCs:", trackedVcs.size);
      // Per-tracked-VC visibility: do we have voice state for it?
      // This is the smoking gun for "0/5 when people are there" --
      // if the VC is tracked but voiceStates lacks an entry, op 14
      // didn't actually subscribe us to events for that VC's guild.
      console.log("\nTracked VC voice-state visibility:");
      for (const vcId of trackedVcs) {
        const ch = GW.channels.get(vcId);
        const hasState = GW.voiceStates.has(vcId);
        const count = hasState ? GW.voiceStates.get(vcId).size : "(no state)";
        console.log(`  ${vcId} ${ch?.name || "?"} guild=${ch?.guild_id || "?"} users=${count}`);
      }
      console.log("\nSample channels:");
      let i = 0;
      for (const [id, ch] of GW.channels) {
        if (i++ >= 5) break;
        console.log(`  ${id} ${ch.name} (type=${ch.type} limit=${ch.user_limit || "∞"})`);
      }
      // Return a structured object so the user can copy-paste it.
      return {
        version: USERSCRIPT_VERSION,
        stats: { ...stats },
        ready: GW.ready,
        meId: GW.meId,
        subscribedGuilds: Array.from(subscribedGuilds),
        trackedVcs: Array.from(trackedVcs).map((id) => {
          const ch = GW.channels.get(id);
          const stateSet = GW.voiceStates.get(id);
          return {
            id,
            name: ch?.name || null,
            guild_id: ch?.guild_id || null,
            user_limit: ch?.user_limit || null,
            users_in_state: stateSet ? stateSet.size : null,
            user_ids: stateSet ? Array.from(stateSet) : null,
          };
        }),
      };
    };

  // ============================================================================
  // Gateway message handler
  // ============================================================================

  function handleGatewayMessage(payload) {
    stats.gateway_events++;
    // op 0 = dispatch (most things). Other ops are heartbeat/identify/etc.
    if (payload.op !== 0) return;

    const t = payload.t;
    const d = payload.d;
    if (!d) return;

    // Diagnostic: count every event type we observe. Helps debug
    // missed/unhandled events when voice counts go stale.
    if (!stats.event_types) stats.event_types = {};
    stats.event_types[t] = (stats.event_types[t] || 0) + 1;

    switch (t) {
      case "READY":
        GW.meId = d.user?.id || null;
        for (const guild of d.guilds || []) {
          ingestGuild(guild);
        }
        GW.ready = true;
        // After READY, we know definitively whether we're in voice.
        // ingestGuild fans out voice_states through handleVoiceStateUpdate,
        // which sets __bnet_self_in_voice = true if our user_id appears.
        // If it's still undefined here, we are not in any voice channel.
        try {
          if (unsafeWindow.__bnet_self_in_voice === undefined) {
            unsafeWindow.__bnet_self_in_voice = false;
          }
        } catch (_) {}
        log(
          "gateway READY: meId=" +
            GW.meId +
            ", guilds=" +
            (d.guilds?.length || 0) +
            ", channels=" +
            GW.channels.size +
            ", inVoice=" +
            (unsafeWindow.__bnet_self_in_voice ? "yes" : "no")
        );
        // We DON'T blanket-subscribe to every guild's voice events on
        // READY anymore. For huge guilds (OW has 100k+ members) the
        // empty-channels op 14 subscribe is rejected -- Discord only
        // streams voice state when you specify which channels you
        // care about with member-range arrays.
        //
        // Instead, subscribeToGuildVoice gets called from
        // postLfgMessage (and from backfill, which also calls
        // postLfgMessage) with the specific VC channel ID. Each LFG
        // therefore upgrades the subscription with the channel
        // ranges Discord requires for voice state delivery.
        break;

      case "READY_SUPPLEMENTAL":
        // Has merged_members / merged_presences; not strictly needed for LFG.
        // Some voice states may live here too on recent Discord versions.
        for (const vs of d.merged_voice_states || []) {
          if (Array.isArray(vs)) {
            for (const v of vs) handleVoiceStateUpdate(v);
          } else {
            handleVoiceStateUpdate(vs);
          }
        }
        break;

      case "RESUMED":
        // Discord just finished replaying events since our last
        // sequence number. If a self VSU was going to arrive, it
        // came in the replay. If __bnet_self_in_voice is still
        // undefined here, no replayed event referenced our user,
        // which (combined with the gateway being live) means we're
        // not in voice.
        try {
          if (unsafeWindow.__bnet_self_in_voice === undefined) {
            unsafeWindow.__bnet_self_in_voice = false;
            log("RESUMED with no self VSU -> in-voice = false");
          }
        } catch (_) {}
        break;

      case "GUILD_CREATE":
        ingestGuild(d);
        break;

      case "CHANNEL_CREATE":
      case "CHANNEL_UPDATE":
        ingestChannel(d);
        break;

      case "CHANNEL_DELETE":
        // If this was a tracked LFG voice channel, the group
        // disbanded -- Discord auto-cleans empty VCs once the LFG
        // bot's lifecycle ends. Notify bnetswitch to drop any LFG
        // messages referencing this VC (otherwise the TUI shows a
        // stale "5/5" row for a VC that no longer exists).
        if (trackedVcs.has(d.id)) {
          trackedVcs.delete(d.id);
          GW.voiceStates.delete(d.id);
          bnetRequest("POST", "/voice/deleted", { channel_id: d.id })
            .catch((e) => debug("voice-deleted push failed:", e.message));
        }
        GW.channels.delete(d.id);
        break;

      case "VOICE_STATE_UPDATE":
        // Single-state form (legacy / smaller guilds).
        handleVoiceStateUpdate(d);
        break;

      case "VOICE_STATE_UPDATE_BATCH":
        // Modern Discord rolls multiple voice state changes into a
        // single batch event. WITHOUT THIS HANDLER VOICE COUNTS GO
        // STALE: post-READY voice events come exclusively as batches
        // for large guilds (OW), so the singular VOICE_STATE_UPDATE
        // never fires and our voiceStates Map drifts from reality.
        //
        // Empirically observed: 9 batch events / 30s in OW guild, 0
        // singular events. Without this dispatch, voice counts only
        // reflect READY_SUPPLEMENTAL's boot snapshot + any backfill
        // from GUILD_MEMBER_LIST_UPDATE.
        //
        // Format: { voice_states: [vs1, vs2, ...] } based on how
        // Discord serializes batched payloads. Fallback to other
        // shapes (just `d` being an array) defensively.
        {
          const batch = Array.isArray(d) ? d : (d.voice_states || []);
          for (const vs of batch) {
            if (vs && vs.user_id) handleVoiceStateUpdate(vs);
          }
        }
        break;

      case "GUILD_MEMBER_LIST_UPDATE":
        // Response to op 14 lazy-guild requests with channel ranges.
        // Discord delivers the visible-member chunks here; some
        // members include a `voice_state` inline. Ingest those so we
        // pick up users who were already in the VC before we sent
        // op 14 (they don't generate VOICE_STATE_UPDATE events
        // because no state CHANGE happened from their perspective).
        //
        // Without this handler, voice counts under-count by however
        // many users joined the VC before our subscribe. After this,
        // op 14 doubles as a "fetch current voice state" call.
        if (d.ops && Array.isArray(d.ops)) {
          for (const op of d.ops) {
            const items = op.items || (op.item ? [op.item] : []);
            for (const it of items) {
              if (it && it.member && it.member.voice_state) {
                const vs = it.member.voice_state;
                handleVoiceStateUpdate({
                  ...vs,
                  user_id: vs.user_id || it.member.user?.id,
                  guild_id: d.guild_id,
                });
              }
            }
          }
        }
        break;

      case "MESSAGE_CREATE":
      case "MESSAGE_UPDATE":
        if (shouldProcessLfgMessage(d)) {
          stats.lfg_posts_observed++;
          postLfgMessage(d);
        }
        break;

      case "MESSAGE_DELETE":
        if (isWatchedChannel(d.channel_id)) {
          postLfgRemove(d.id);
        }
        break;

      case "MESSAGE_DELETE_BULK":
        if (isWatchedChannel(d.channel_id)) {
          for (const id of d.ids || []) postLfgRemove(id);
        }
        break;
    }
  }

  function isWatchedChannel(channelId) {
    if (!channelId) return false;
    if (WATCHED_CHANNEL_IDS.length === 0) return true;
    return WATCHED_CHANNEL_IDS.includes(channelId);
  }

  function shouldProcessLfgMessage(msg) {
    if (!isWatchedChannel(msg.channel_id)) return false;
    if (!msg.author) return false;
    // Two cases match LFG Tool: bot username, or webhook author with that name
    const username = msg.author.username || msg.author.global_name;
    if (username !== LFG_BOT_USERNAME) return false;
    if (!msg.embeds || msg.embeds.length === 0) return false;
    return true;
  }

  function ingestGuild(guild) {
    if (!guild.id) return;
    GW.guilds.set(guild.id, { name: guild.name });

    for (const channel of guild.channels || []) {
      ingestChannel({ ...channel, guild_id: guild.id });
    }

    // Voice states: each user currently in a VC of this guild.
    for (const vs of guild.voice_states || []) {
      handleVoiceStateUpdate({ ...vs, guild_id: guild.id });
    }
  }

  function ingestChannel(channel) {
    if (!channel.id) return;
    GW.channels.set(channel.id, {
      name: channel.name || "",
      type: channel.type,
      user_limit: channel.user_limit || 0,
      guild_id: channel.guild_id,
      parent_id: channel.parent_id || null,
    });
  }

  function handleVoiceStateUpdate(vs) {
    if (!vs.user_id) return;
    stats.voice_state_updates++;

    // Remove the user from their previous VC (if any)
    const prevChannelId = GW.userVoiceChannel.get(vs.user_id);
    if (prevChannelId) {
      const prev = GW.voiceStates.get(prevChannelId);
      if (prev) {
        prev.delete(vs.user_id);
        // KEEP the empty Set even when size hits 0. Deleting it
        // would erase the distinction between "VC is empty" (we know
        // it's empty) and "VC unknown" (we have no info). Downstream
        // count-pushers rely on `voiceStates.has(id)` to mean "we
        // KNOW the count of this VC" -- if true and size==0, it's
        // genuinely empty, push 0. If false, push null (unknown).
        //
        // Memory: empty Sets are tiny (~64 bytes), CHANNEL_DELETE
        // cleans them up when the LFG bot reaps the VC, so this
        // doesn't grow unbounded.
      }
    }

    // Add to the new VC (if any). channel_id is null when leaving voice.
    if (vs.channel_id) {
      if (!GW.voiceStates.has(vs.channel_id)) {
        GW.voiceStates.set(vs.channel_id, new Set());
      }
      GW.voiceStates.get(vs.channel_id).add(vs.user_id);
      GW.userVoiceChannel.set(vs.user_id, vs.channel_id);
    } else {
      GW.userVoiceChannel.delete(vs.user_id);
    }

    // Push the new VC count to bnetswitch in real-time so the LFG
    // view stays accurate as people join/leave. Filter to channels we
    // have outstanding LFG messages for, since most voice activity is
    // unrelated to LFG groups.
    if (prevChannelId && trackedVcs.has(prevChannelId)) {
      schedulePushVoiceCount(prevChannelId);
    }
    if (vs.channel_id && trackedVcs.has(vs.channel_id)) {
      schedulePushVoiceCount(vs.channel_id);
    }

    // Track whether WE are currently in a voice channel. The loader
    // userscript reads `unsafeWindow.__bnet_self_in_voice` to decide
    // whether it's safe to auto-reload the page after caching a new
    // userscript version. Reloading mid-call drops you from voice;
    // this flag prevents that.
    if (GW.meId && vs.user_id === GW.meId) {
      const inVoice = !!vs.channel_id;
      try { unsafeWindow.__bnet_self_in_voice = inVoice; } catch (_) {}
      if (!inVoice) {
        // We just left voice. If the loader has a pending update, this
        // is the moment to apply it.
        try {
          if (typeof unsafeWindow.__bnet_loader_notify_voice_left === "function") {
            unsafeWindow.__bnet_loader_notify_voice_left();
          }
        } catch (_) {}
      }
    }
  }

  // Channels we've seen referenced in an LFG embed. Only push voice
  // updates for these to keep network traffic to a few /sec instead of
  // the whole guild's voice activity.
  const trackedVcs = new Set();

  // Guilds we've subscribed to via op 14 lazy request. We send the
  // subscribe once per guild on first sighting of an LFG embed in that
  // guild, then remember to avoid duplicate subscribes. Without the op
  // 14 subscription, Discord's gateway won't send VOICE_STATE_UPDATE
  // events for guilds the user isn't actively in voice in -- meaning
  // VC member counts never refresh after the initial post snapshot.
  const subscribedGuilds = new Set();
  // Tracks which (guild, channel) pairs we've already requested ranges
  // for. Discord scales op 14 subscriptions per channel; sending the
  // same channel twice is a no-op but burns bandwidth.
  const subscribedChannels = new Set(); // "guild_id:channel_id"
  function subscribeToGuildVoice(guildId, vcChannelId) {
    if (!guildId) return;
    const channelKey = vcChannelId ? `${guildId}:${vcChannelId}` : null;
    const haveGuild = subscribedGuilds.has(guildId);
    const haveChannel = channelKey ? subscribedChannels.has(channelKey) : true;
    if (haveGuild && haveChannel) return;
    subscribedGuilds.add(guildId);
    if (channelKey) subscribedChannels.add(channelKey);
    // Build channels map: Discord large guilds (100k+ members like
    // the OW guild) require per-channel range subscriptions to start
    // streaming voice/presence events. Empty `channels: {}` returns
    // basic guild metadata but no voice state stream. Including the
    // specific LFG VC channel triggers GUILD_MEMBERS_CHUNK and
    // VOICE_STATE_UPDATE delivery for it.
    //
    // Range [[0, 99]] = top-100 members visible. Any positive range
    // works for our purposes -- we just need Discord to flag the
    // channel as "actively viewed" so voice events flow.
    const channels = {};
    if (vcChannelId) channels[vcChannelId] = [[0, 99]];
    try {
      document.dispatchEvent(
        new CustomEvent("__bnetswitch_subscribe_guild__", {
          detail: { guild_id: guildId, channels },
        })
      );
      log("subscribed to guild voice events:", guildId,
          vcChannelId ? `(vc ${vcChannelId})` : "(guild only)");
    } catch (e) {
      debug("guild subscribe dispatch failed:", e.message);
    }
  }

  // Coalesce rapid-fire VOICE_STATE_UPDATE events: in burst scenarios
  // (whole stack joining at once) we'd otherwise fire N requests for
  // the same channel with sequential counts. Debounce per-channel so
  // only the latest count is sent.
  const pendingVcPush = new Map(); // channel_id -> timeout handle
  function schedulePushVoiceCount(channelId) {
    if (pendingVcPush.has(channelId)) return;
    const handle = setTimeout(() => {
      pendingVcPush.delete(channelId);
      pushVoiceCount(channelId);
    }, 200);
    pendingVcPush.set(channelId, handle);
  }

  function pushVoiceCount(channelId) {
    // Three-way semantic for `users`:
    //   number  -> we KNOW the count (state map has an entry, even if
    //              empty after the keep-empty-Set fix)
    //   0       -> VC exists, currently empty
    //   null    -> we don't know yet (op 14 subscribe pending, or VC
    //              not in our channel cache at all)
    //
    // Without the keep-empty-Set behavior, "size 0 after last user
    // left" would be indistinguishable from "no info", and we'd
    // regress to confidently lying with 0/5.
    const ch = GW.channels.get(channelId);
    const stateSet = GW.voiceStates.get(channelId);
    let users;
    if (stateSet) {
      users = stateSet.size;          // known: 0+
    } else if (ch) {
      // VC exists in channel cache, no voice state entry. With the
      // empty-Set fix this implies "we never received a VSU for this
      // VC" (boot race, op 14 still pending). Don't lie -- send null.
      users = null;
    } else {
      // VC not in channel cache at all. Either deleted or we never
      // saw CHANNEL_CREATE for it. Definitely unknown.
      users = null;
    }
    bnetRequest("POST", "/voice/state", {
      channel_id: channelId,
      users,
      capacity: ch?.user_limit || null,
    }).catch((e) => debug("voice-state push failed:", e.message));
  }

  // ============================================================================
  // LFG message extraction (from gateway JSON, not DOM)
  // ============================================================================

  function postLfgMessage(msg) {
    const embed = msg.embeds[0];
    if (!embed) return;

    // Voice Channel field uses Discord's <#channel_id> mention syntax
    let vcChannelId = null;
    if (embed.fields) {
      for (const f of embed.fields) {
        if (!f.name || !f.name.toLowerCase().includes("voice channel")) continue;
        const m = (f.value || "").match(/<#(\d+)>/);
        if (m) {
          vcChannelId = m[1];
          break;
        }
      }
    }

    // Cross-reference our channel cache for name + capacity.
    // Distinguish "0 users" (we have voice state, the VC is empty)
    // from "unknown" (no voice state yet -- lazy subscribe pending).
    // See pushVoiceCount for why null != 0 here.
    const vcChannel = vcChannelId ? GW.channels.get(vcChannelId) : null;

    // Zombie-VC detection: if the LFG references a VC that's NOT in
    // our channel cache, AND we've already received GUILD_CREATE for
    // the LFG's guild (so channel cache is fully populated), the VC
    // was deleted before we connected -- group disbanded already.
    // Tell bnetswitch to drop this message and skip forwarding.
    //
    // Without this check, REST-backfilled LFGs from before our
    // session started accumulate as ghost rows in the TUI, all
    // showing "?/?" with no rank info and no joinable VC.
    //
    // Guard with the GW.guilds.has check to avoid false positives
    // during the brief window between READY and the first
    // GUILD_CREATE -- otherwise EVERY backfill LFG would look like
    // a zombie before its guild data arrives.
    const lfgGuildIdEarly =
      msg.guild_id || GW.channels.get(msg.channel_id)?.guild_id;
    if (vcChannelId && !vcChannel && lfgGuildIdEarly && GW.guilds.has(lfgGuildIdEarly)) {
      debug("zombie LFG (VC", vcChannelId, "deleted), removing:", msg.id);
      stats.zombie_lfgs_dropped = (stats.zombie_lfgs_dropped || 0) + 1;
      bnetRequest("POST", "/voice/deleted", { channel_id: vcChannelId })
        .catch((e) => debug("zombie cleanup failed:", e.message));
      // Don't forward this LFG -- it's already dead.
      return;
    }

    let vcUsers = null;
    if (vcChannelId) {
      const stateSet = GW.voiceStates.get(vcChannelId);
      if (stateSet) {
        vcUsers = stateSet.size;     // known: 0+
      } else if (vcChannel) {
        vcUsers = null;              // exists, no state yet
      } else {
        vcUsers = null;              // unknown VC
      }
    }
    const vcCapacity = vcChannel?.user_limit || null;
    const vcName = vcChannel?.name || null;

    // Mark this VC as "tracked" so future VOICE_STATE_UPDATE events
    // push updated counts to bnetswitch in real time. Also push the
    // CURRENT count immediately, which fixes backfilled LFG entries
    // whose counts were captured at post-time and have since gone
    // stale. Safe to call repeatedly: bnetswitch idempotently writes
    // to all messages with this voice_channel_id.
    if (vcChannelId) {
      const isNewlyTracked = !trackedVcs.has(vcChannelId);
      trackedVcs.add(vcChannelId);
      // Only push when we have at least some gateway data (READY/
      // GUILD_CREATE has populated voiceStates). Otherwise we'd push
      // 0 for VCs we just haven't seen state for yet, briefly
      // overwriting the post-time snapshot with a false 0.
      if (isNewlyTracked && GW.voiceStates.has(vcChannelId)) {
        schedulePushVoiceCount(vcChannelId);
      }
    }

    // Subscribe to voice events for this guild if we haven't already.
    // The guild_id comes from either the message itself OR the channel
    // record. Without this subscription, Discord's gateway never sends
    // VOICE_STATE_UPDATE events for VCs in this guild (unless we're
    // currently in voice in this guild), and the counts above will
    // never refresh past their initial post-time snapshot.
    const lfgGuildId =
      msg.guild_id ||
      GW.channels.get(msg.channel_id)?.guild_id ||
      (vcChannel && vcChannel.guild_id);
    if (lfgGuildId) {
      // Pass the LFG's VC ID so the subscribe includes it in the
      // channels-with-ranges map. Without that, large guilds (OW has
      // 100k+ members) won't stream voice events -- just empty
      // metadata. With it, we get GUILD_MEMBERS_CHUNK + voice state
      // updates for that specific VC.
      subscribeToGuildVoice(lfgGuildId, vcChannelId);
    }

    // Join Voice button URL is in the message components (Discord's
    // structured interaction button format).
    let vcUrl = null;
    for (const row of msg.components || []) {
      for (const btn of row.components || []) {
        if (btn.label === "Join Voice" && btn.url) {
          vcUrl = btn.url;
          break;
        }
      }
      if (vcUrl) break;
    }

    // Build the wire-format payload bnetswitch expects. Field names match
    // bnetswitch/src/lfg.rs::LfgMessage exactly.
    const payload = {
      message_id: msg.id,
      channel_id: msg.channel_id,
      channel_name: GW.channels.get(msg.channel_id)?.name || "unknown",
      author: embed.author?.name || msg.author.username || "unknown",
      title: embed.author?.name || null,
      // Description: same mention-stripping treatment as field values.
      // Without this, raw `<:Silver:1272...>` and `<#chan_id>` markup
      // leaks through to the TUI and clutters the description line.
      description: resolveMentions(embed.description || null),
      fields: (embed.fields || []).map((f) => ({
        name: f.name || "",
        value: resolveMentions(f.value || ""),
      })),
      timestamp_ms: Date.parse(msg.edited_timestamp || msg.timestamp) || Date.now(),
      voice_channel_users: vcUsers,
      voice_channel_capacity: vcCapacity,
      voice_channel_id: vcChannelId,
      voice_channel_url: vcUrl,
      guild_id: msg.guild_id || null,
    };

    debug("posting LFG", payload.author, payload.description, vcUsers + "/" + vcCapacity);
    stats.posts_attempted++;
    bnetRequest("POST", "/lfg/message", payload)
      .then(() => {
        stats.posts_succeeded++;
        stats.lfg_posts_forwarded++;
      })
      .catch((e) => {
        stats.posts_failed++;
        warn("post /lfg/message failed:", e.message);
      });
  }

  function postLfgRemove(messageId) {
    debug("posting LFG removal", messageId);
    bnetRequest("POST", "/lfg/remove", { message_id: messageId }).catch((e) =>
      warn("post /lfg/remove failed:", e.message)
    );
  }

  /** Strip / resolve Discord's mention syntax in embed strings.
   *
   * Discord embeds emit raw mention markup that's only meaningful with
   * a live mention-resolver (the React rendering pipeline). When we
   * forward strings to a plain TUI, the markup leaks through as
   * unreadable noise like `<:Silver:1272892588453658796>` or
   * `<#1501058773...>`. Convert each to a human-friendly form.
   *
   * Mention forms (per discord.com/developers/docs/reference#message-formatting):
   *   <#id>            -> channel name (or "#unknown" if not cached)
   *   <:name:id>       -> :name:        (custom emoji)
   *   <a:name:id>      -> :name:        (animated custom emoji)
   *   <@id> / <@!id>   -> @username (best-effort) else "@user"
   *   <@&id>           -> @rolename (best-effort) else "@role"
   *   <t:unix[:fmt]>   -> human time (we just keep the raw timestamp)
   */
  function resolveMentions(text) {
    if (!text) return text;
    let out = text;
    // <#channel_id> -- replace with channel name when cached, else
    // a stable short placeholder so the raw 18-digit ID doesn't blow
    // up column widths.
    out = out.replace(/<#(\d+)>/g, (match, id) => {
      const ch = GW.channels.get(id);
      return ch ? ch.name : "#unknown";
    });
    // <:name:id> and <a:name:id> -- collapse to :name:
    out = out.replace(/<a?:([A-Za-z0-9_]+):\d+>/g, ":$1:");
    // <@user_id> / <@!user_id>
    out = out.replace(/<@!?(\d+)>/g, (match, id) => {
      const u = GW.users && GW.users.get && GW.users.get(id);
      return u ? `@${u.username || u.global_name || "user"}` : "@user";
    });
    // <@&role_id>
    out = out.replace(/<@&(\d+)>/g, "@role");
    return out;
  }

  // ============================================================================
  // WebSocket patch via main-world script injection
  //
  // Why this is more complex than a direct `unsafeWindow.WebSocket = ...`
  // assignment:
  //
  //   - In Firefox, Tampermonkey runs scripts in a security sandbox that
  //     wraps `unsafeWindow`. Assigning to `unsafeWindow.WebSocket` does
  //     not actually replace what the PAGE sees as `window.WebSocket`.
  //   - In Chromium with Manifest V3 user-scripts mode, similar isolation
  //     applies. Even when our patch "works" via unsafeWindow, the page's
  //     bundle may have captured a reference to the original constructor
  //     before our script ran.
  //
  // Workaround that works in both: inject an actual <script> element into
  // the page. Its contents run in the page's main world with the same
  // privileges as Discord's own bundle. This is the same technique used
  // by BetterDiscord, Vencord, every Discord-modding userscript.
  //
  // The injected script bridges gateway events back to us via
  // window.postMessage, which crosses content-script boundaries cleanly
  // in every browser.
  // ============================================================================

  const BRIDGE_MSG_TYPE = "__bnetswitch_lfg_gw__";

  function injectGatewayTap() {
    // The code below runs in the page's main world (where Discord's
    // bundle lives). It MUST be self-contained -- no closures over our
    // userscript variables.
    //
    // CRITICAL CONTEXT FOR FUTURE ME:
    //   Despite Discord's [FAST CONNECT] log messages suggesting a
    //   SharedWorker is involved, in 2026's stable build the gateway
    //   WebSocket is just a plain main-thread `new WebSocket(...)`. The
    //   "fast connect" name refers to how Discord's bundle pre-fetches
    //   gateway URLs from /api/v9/gateway, not to cross-tab WS sharing.
    //   We verified empirically: 0 SharedWorkers, 0 BroadcastChannels.
    //
    //   The race we DO need to handle: with @run-at document-start under
    //   Chromium MV3 + Tampermonkey, our patches install AFTER Discord's
    //   bundle has already started fetching its main script. The first
    //   gateway WebSocket is created BEFORE our PatchedWS constructor is
    //   in place (Discord caches `WebSocket` early). Only the PROTOTYPE
    //   patches catch messages on that first WS, and we miss the very
    //   first compressed frames so we can't decode subsequent ones.
    //
    //   SOLUTION: force-close that first WS once. Discord auto-reconnects
    //   THROUGH our PatchedWS this time, which strips compress=zlib-stream
    //   from the URL. The new connection sends plain JSON text frames we
    //   can parse directly without decompression.
    const code = `
      (function() {
        if (window.__bnetswitch_patched) return;
        window.__bnetswitch_patched = true;

        const stats = {
          ws_ctor_calls: 0,
          ws_gateway_calls: 0,
          ws_gateway_messages: 0,
          wsproto_listeners_wrapped: 0,
          wsproto_messages: 0,
          wsproto_gateway_messages: 0,
          wsproto_gateway_urls: [],
          wsproto_string_msgs: 0,
          wsproto_arraybuffer_msgs: 0,
          wsproto_blob_msgs: 0,
          wsproto_json_parsed: 0,
          wsproto_parse_failed: 0,
        };
        window.__bnetswitch_ws_stats = stats;

        const BRIDGE_TYPE = ${JSON.stringify(BRIDGE_MSG_TYPE)};
        const BRIDGE_BINARY_TYPE = ${JSON.stringify(BRIDGE_MSG_TYPE + "_bin")};
        const BRIDGE_EVENT_NAME = '__bnetswitch_lfg_event__';

        // CRITICAL: In Chromium MV3 + Tampermonkey, page-world
        // window.postMessage does NOT propagate to userscript-world
        // window.addEventListener('message'). The two worlds have separate
        // message channels even though the window object appears shared.
        //
        // We use CustomEvent on document instead -- DOM events fire across
        // worlds reliably because the DOM is the shared substrate.
        function bridgeDispatch(detail) {
          document.dispatchEvent(new CustomEvent(BRIDGE_EVENT_NAME, { detail }));
        }

        function bridgeGatewayMessage(payload) {
          bridgeDispatch({
            __bnet_type: BRIDGE_TYPE,
            event: 'message',
            payload: payload,
          });
        }

        // Forward raw zlib-compressed binary frames to the userscript world,
        // where pako (loaded via @require) lives and can decode the
        // streaming context. Each WS instance gets a unique id so the
        // userscript can keep a per-WS pako.Inflate.
        //
        // CRITICAL: For Discord's compress=zlib-stream, the first WS we
        // see is mid-stream -- HELLO and earlier frames were consumed by
        // Discord's listener before our prototype patch wrapped it (race
        // at document-start with MV3 user-scripts injection). Without the
        // prior frames' content we can't build the LZ77 sliding window,
        // so deflate fails with "invalid distance too far back". Solution:
        // force-close the first WS once. Discord reconnects with a fresh
        // deflate stream; the new WS goes through our wrapper from frame
        // 1 and we can decode from there.
        let __bnet_next_ws_id = 1;
        let __bnet_did_force_reconnect = false;
        const __bnet_ws_ids = new WeakMap();
        function bridgeBinaryGateway(ws, ab) {
          let id = __bnet_ws_ids.get(ws);
          if (id == null) {
            id = __bnet_next_ws_id++;
            __bnet_ws_ids.set(ws, id);
            bridgeDispatch({
              __bnet_type: BRIDGE_BINARY_TYPE,
              event: 'open',
              wsId: id,
              url: ws.url,
              isFirstAfterReconnect: __bnet_did_force_reconnect,
            });

            // On the very first gateway WS we see, force a reconnect so
            // we catch the deflate stream from the start. Subsequent WSs
            // (after reconnect) we let through normally.
            if (!__bnet_did_force_reconnect) {
              __bnet_did_force_reconnect = true;
              const target = ws;
              // Slight delay so Discord finishes initial setup; close
              // outside the message handler to avoid reentrancy.
              setTimeout(() => {
                try {
                  if (target.readyState === 1) {
                    console.log('[bnetswitch-lfg-injected] forcing gateway reconnect to capture deflate stream from start');
                    // 4000-4999 are application-defined close codes;
                    // Discord treats them as resumable.
                    target.close(4000, 'bnet-reset');
                  }
                } catch (e) {
                  console.log('[bnetswitch-lfg-injected] force-close failed:', e.message);
                }
              }, 50);
            }
          }
          // CustomEvent details cross worlds via structured cloning. The
          // ArrayBuffer is cloned (not transferred) but cost is acceptable
          // for ~10 KB/s gateway traffic.
          bridgeDispatch({
            __bnet_type: BRIDGE_BINARY_TYPE,
            event: 'binary',
            wsId: id,
            buffer: ab,
          });
        }

        // Discord gateway messages have shape { op, d, t?, s? }.
        function looksLikeGatewayMessage(data) {
          if (!data || typeof data !== 'object') return false;
          if (typeof data.op !== 'number') return false;
          // Op 0 dispatches have t (event name) and s (sequence). Other
          // ops (heartbeat, hello, etc.) have op only. Both are valid
          // gateway frames.
          return true;
        }

        // Match both gateway.discord.gg and regional shards like
        // gateway-us-east1-c.discord.gg (used by Discord after RESUME).
        const GATEWAY_URL_RE = /gateway[a-z0-9-]*\.discord\.gg/i;

        // ====================================================================
        // PATCH 1: window.WebSocket
        // Catches direct gateway connections (rare with Fast Connect).
        // ====================================================================
        const Original = window.WebSocket;
        if (Original) {
          // CRITICAL: do NOT modify the gateway URL. Discord's bundle has
          // its decompressor (eu.feed) wired up based on its own config,
          // not based on the URL. If we strip compress=zlib-stream, Discord
          // still feeds incoming string frames into its zlib decoder which
          // throws "Expected array buffer, but got string", breaking the
          // gateway entirely. Pass the URL through unchanged; we'll
          // decompress the binary frames ourselves.
          function PatchedWS(url, protocols) {
            stats.ws_ctor_calls++;
            const isGateway = typeof url === 'string' && GATEWAY_URL_RE.test(url);
            if (isGateway) {
              stats.ws_gateway_calls++;
              console.log('[bnetswitch-lfg-injected] gateway connect (direct WS)', url);
            }
            const ws = protocols !== undefined
              ? new Original(url, protocols)
              : new Original(url);
            return ws;
          }
          PatchedWS.prototype = Original.prototype;
          ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach((k) => {
            PatchedWS[k] = Original[k];
          });
          window.WebSocket = PatchedWS;
        }

        // ====================================================================
        // PATCH 1b: WebSocket.prototype.addEventListener + onmessage
        // Even if Discord cached the original WebSocket constructor before
        // our userscript ran (possible with @run-at document-start +
        // module preload), instances still use the prototype's methods to
        // attach listeners. This catches ALL WebSocket message events
        // regardless of whose constructor reference was used.
        // ====================================================================
        if (window.WebSocket) {
          const WSProto = WebSocket.prototype;
          const origWSAdd = WSProto.addEventListener;
          const origWSOnMsgDesc = Object.getOwnPropertyDescriptor(WSProto, 'onmessage');

          function wrapWSListener(listener) {
            if (!listener) return listener;
            if (listener.__bnet_wsp_wrapped) return listener.__bnet_wsp_wrapped;
            const wrapped = function(event) {
              stats.wsproto_messages++;
              try {
                let isGw = false;
                try {
                  if (this.url && GATEWAY_URL_RE.test(this.url)) {
                    isGw = true;
                    if (!stats.wsproto_gateway_urls.includes(this.url)) {
                      stats.wsproto_gateway_urls.push(this.url);
                      console.log('[bnetswitch-lfg-injected] gateway WS via prototype patch:', this.url);
                    }
                  }
                } catch (e) {}
                if (isGw) {
                  stats.wsproto_gateway_messages++;
                  const d = event.data;
                  if (typeof d === 'string') {
                    stats.wsproto_string_msgs++;
                    try {
                      bridgeGatewayMessage(JSON.parse(d));
                      stats.wsproto_json_parsed++;
                    } catch (e) {
                      stats.wsproto_parse_failed++;
                    }
                  } else if (d instanceof ArrayBuffer) {
                    stats.wsproto_arraybuffer_msgs++;
                    // Forward to userscript world for pako-based streaming
                    // inflate (we don't have pako in page world).
                    try {
                      // Slice to a fresh AB so we can transfer ownership.
                      const copy = d.slice(0);
                      bridgeBinaryGateway(this, copy);
                    } catch (e) {
                      stats.wsproto_parse_failed++;
                    }
                  } else if (d instanceof Blob) {
                    stats.wsproto_blob_msgs++;
                    const ws = this;
                    d.arrayBuffer().then(ab => {
                      try { bridgeBinaryGateway(ws, ab); }
                      catch (e) { stats.wsproto_parse_failed++; }
                    }).catch(() => { stats.wsproto_parse_failed++; });
                  } else {
                    stats.wsproto_other_msgs++;
                  }
                }
              } catch (e) {}
              return listener.call(this, event);
            };
            listener.__bnet_wsp_wrapped = wrapped;
            return wrapped;
          }

          WSProto.addEventListener = function(type, listener, options) {
            if (type === 'message' && typeof listener === 'function') {
              stats.wsproto_listeners_wrapped++;
              // Capture latest gateway WS reference so we can send op 4
              // (Voice State Update) to auto-join voice channels later.
              if (this.url && GATEWAY_URL_RE.test(this.url)) {
                window.__bnet_gw_ws = this;
              }
              return origWSAdd.call(this, type, wrapWSListener(listener), options);
            }
            return origWSAdd.call(this, type, listener, options);
          };

          if (origWSOnMsgDesc && origWSOnMsgDesc.set) {
            Object.defineProperty(WSProto, 'onmessage', {
              configurable: true,
              enumerable: origWSOnMsgDesc.enumerable,
              get() { return origWSOnMsgDesc.get?.call(this); },
              set(handler) {
                if (typeof handler === 'function') {
                  stats.wsproto_listeners_wrapped++;
                  if (this.url && GATEWAY_URL_RE.test(this.url)) {
                    window.__bnet_gw_ws = this;
                  }
                  return origWSOnMsgDesc.set.call(this, wrapWSListener(handler));
                }
                return origWSOnMsgDesc.set.call(this, handler);
              },
            });
          }
        }

        // ====================================================================
        // Voice-state-update bridge: userscript world dispatches a custom
        // event with {guild_id, channel_id}; we send op 4 over the gateway
        // WS. This triggers the same server-side action as clicking the
        // blue channel-mention link in an LFG embed -- Discord's bundle
        // picks up the resulting VOICE_STATE_UPDATE and connects WebRTC,
        // so we end up actually joined to the VC. Beats pushState (which
        // only navigates without joining).
        // ====================================================================
        document.addEventListener('__bnetswitch_voice_state__', function(event) {
          const detail = event.detail || {};
          const ws = window.__bnet_gw_ws;
          if (!ws) {
            console.log('[bnetswitch-lfg-injected] voice-state-update: no gateway WS captured yet');
            return;
          }
          if (ws.readyState !== 1) {
            console.log('[bnetswitch-lfg-injected] voice-state-update: WS not OPEN (state=' + ws.readyState + ')');
            return;
          }
          try {
            const payload = JSON.stringify({
              op: 4,
              d: {
                guild_id: detail.guild_id || null,
                channel_id: detail.channel_id || null,
                self_mute: !!detail.self_mute,
                self_deaf: !!detail.self_deaf,
              },
            });
            ws.send(payload);
            console.log(
              '[bnetswitch-lfg-injected] sent op 4 voice state update',
              detail.guild_id, '->', detail.channel_id
            );
          } catch (e) {
            console.log('[bnetswitch-lfg-injected] voice state update send failed:', e.message);
          }
        });

        // ====================================================================
        // Lazy-guild subscription bridge (op 14):
        //
        // Discord gateway only emits VOICE_STATE_UPDATE for guilds the user
        // is engaged with: currently in voice OR has an explicit lazy-guild
        // subscription open. Without this, MESSAGE_CREATE events from the
        // LFG bot fine (channel-level subscribed via just being in the
        // guild), but VC-member-count changes never reach us. So
        // bnetswitch voice_channel_users counts freeze at post-time
        // snapshot.
        //
        // Web client uses the "Lazy Request" opcode 14 with activities:true
        // to receive voice/presence updates for a guild without joining a
        // voice channel. We dispatch this from userscript world via
        // CustomEvent; this page-world handler writes it to the gateway WS.
        // ====================================================================
        document.addEventListener('__bnetswitch_subscribe_guild__', function(event) {
          const detail = event.detail || {};
          const ws = window.__bnet_gw_ws;
          if (!ws) return;
          if (ws.readyState !== 1) return;
          if (!detail.guild_id) return;
          try {
            const payload = JSON.stringify({
              op: 14,
              d: {
                guild_id: detail.guild_id,
                typing: false,
                activities: true,
                threads: false,
                channels: detail.channels || {},
                members: detail.members || [],
              },
            });
            ws.send(payload);
            console.log(
              '[bnetswitch-lfg-injected] sent op 14 lazy guild subscribe for',
              detail.guild_id
            );
          } catch (e) {
            console.log('[bnetswitch-lfg-injected] guild subscribe failed:', e.message);
          }
        });

        // ====================================================================
        // Auth token capture: hook XMLHttpRequest.setRequestHeader and
        // window.fetch's headers init so we can intercept Discord's
        // bearer token. Used by the userscript-world backfill to query
        // /api/v9/channels/<id>/messages without re-authenticating.
        // ====================================================================
        const origSetHdr = XMLHttpRequest.prototype.setRequestHeader;
        XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
          try {
            if (name && typeof name === 'string' && typeof value === 'string') {
              const ln = name.toLowerCase();
              if (ln === 'authorization' && value && window.__bnet_auth_token !== value) {
                window.__bnet_auth_token = value;
                document.dispatchEvent(new CustomEvent('__bnetswitch_auth_captured__', {
                  detail: { token: value, source: 'xhr' },
                }));
              }
              if (ln === 'x-super-properties') window.__bnet_super_props = value;
              if (ln === 'x-discord-locale') window.__bnet_locale = value;
            }
          } catch (e) {}
          return origSetHdr.call(this, name, value);
        };

        const origFetch = window.fetch;
        window.fetch = function(input, init) {
          try {
            if (init && init.headers) {
              const h = init.headers instanceof Headers
                ? init.headers
                : new Headers(init.headers || {});
              const auth = h.get('authorization');
              if (auth && window.__bnet_auth_token !== auth) {
                window.__bnet_auth_token = auth;
                document.dispatchEvent(new CustomEvent('__bnetswitch_auth_captured__', {
                  detail: { token: auth, source: 'fetch' },
                }));
              }
              const sp = h.get('x-super-properties');
              if (sp) window.__bnet_super_props = sp;
              const loc = h.get('x-discord-locale');
              if (loc) window.__bnet_locale = loc;
            }
          } catch (e) {}
          return origFetch.call(this, input, init);
        };

        window.__bnetswitch_patched_at = Date.now();
        console.log(
          '[bnetswitch-lfg-injected] WS constructor + WS.prototype patched at',
          window.__bnetswitch_patched_at
        );
      })();
    `;

    // Use GM_addElement when available -- it bypasses Discord's strict
    // CSP because the userscript-manager extension adds the element
    // with privileged origin. Falls back to plain createElement which
    // works in any browser without strict CSP (and is what runs in our
    // playwright Chromium dev environment).
    if (typeof GM_addElement === "function") {
      try {
        GM_addElement("script", { textContent: code });
        return;
      } catch (e) {
        warn("GM_addElement failed, falling back to manual injection:", e.message);
      }
    }

    const s = document.createElement("script");
    s.textContent = code;
    s.setAttribute("data-injector", "bnetswitch-lfg");
    (document.head || document.documentElement).appendChild(s);
    s.remove();
  }

  // Run injection immediately at document-start, BEFORE Discord's bundle.
  injectGatewayTap();

  // ============================================================================
  // Cross-world event bridge (userscript world side)
  //
  // The page-world script forwards gateway events two ways:
  //   1. As parsed JSON objects (BRIDGE_MSG_TYPE) -- this is the common path
  //      because we force-reconnect the gateway at startup and our PatchedWS
  //      strips compress=zlib-stream from the URL, so Discord receives plain
  //      JSON text frames after that.
  //   2. As raw ArrayBuffer chunks (BRIDGE_BINARY_TYPE) -- backup for when
  //      our reconnect doesn't take effect (eg cached WebSocket constructor).
  //      Decoded here via DecompressionStream('deflate-raw').
  //
  // We use CustomEvent on document for cross-world IPC because in Chromium
  // MV3 + Tampermonkey, page-world window.postMessage does NOT propagate to
  // userscript-world window.addEventListener('message'). DOM events do.
  // ============================================================================
  const BRIDGE_BINARY_TYPE = BRIDGE_MSG_TYPE + "_bin";
  const BRIDGE_EVENT_NAME = "__bnetswitch_lfg_event__";
  const ZLIB_SUFFIX = [0x00, 0x00, 0xff, 0xff];
  const inflaters = new Map(); // wsId -> { writer, reader, buffer, ... }
  const decoder = new TextDecoder("utf-8");

  // Lightweight debug counters exposed via unsafeWindow so the dev can
  // probe pipeline health from the page-world (Playwright eval, devtools).
  const usw = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;
  const usDebug = {
    pako_loaded: typeof pako !== "undefined",
    bridge_msg_received: 0,
    bridge_bin_received: 0,
    inflater_count: 0,
    inflate_finals: 0,
    inflate_json_ok: 0,
    inflate_pako_err: 0,
    last_pako_err: null,
    ws_first_frames: {},  // wsId -> first8 bytes hex
    ws_modes_tried: {},  // wsId -> { deflate, deflate-raw }
  };
  try { usw.__bnetswitch_us_debug = usDebug; } catch (e) {}

  function endsWithSyncMarker(u8) {
    const n = u8.length;
    if (n < 4) return false;
    return (
      u8[n - 4] === ZLIB_SUFFIX[0] &&
      u8[n - 3] === ZLIB_SUFFIX[1] &&
      u8[n - 2] === ZLIB_SUFFIX[2] &&
      u8[n - 1] === ZLIB_SUFFIX[3]
    );
  }

  // Pull complete top-level JSON objects out of an accumulated text
  // buffer, returning the parsed objects + any incomplete trailing
  // remainder (which the caller should keep for the next flush).
  // Multiple gateway messages can appear in our buffer between sync-
  // marker checks because the DecompressionStream reader is async and
  // may flush several frames worth of decoded text before we look.
  function extractJsonObjects(text) {
    const objects = [];
    let depth = 0;
    let start = -1;
    let inString = false;
    let escape = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (escape) { escape = false; continue; }
      if (inString) {
        if (c === "\\") escape = true;
        else if (c === "\"") inString = false;
        continue;
      }
      if (c === "\"") { inString = true; continue; }
      if (c === "{") {
        if (depth === 0) start = i;
        depth++;
      } else if (c === "}") {
        depth--;
        if (depth === 0 && start >= 0) {
          objects.push(text.slice(start, i + 1));
          start = -1;
        }
      }
    }
    const remainder = depth > 0 && start >= 0 ? text.slice(start) : "";
    return { objects, remainder };
  }

  // Streaming inflate via native DecompressionStream. Discord's
  // compress=zlib-stream is supposed to be zlib-wrapped per protocol,
  // but in practice we've observed both formats on different connections.
  // We try both: 'deflate' (zlib-wrapped) first, fall back to 'deflate-raw'
  // on the FIRST decompression error.
  function makeInflater(wsId, format) {
    format = format || "deflate";
    let stream;
    try {
      stream = new DecompressionStream(format);
    } catch (e) {
      warn("DecompressionStream not supported for", format, ":", e.message);
      return null;
    }
    const state = {
      wsId,
      format,
      buffer: "",
      writer: stream.writable.getWriter(),
      reader: stream.readable.getReader(),
      tried_formats: [format],
    };
    (async () => {
      try {
        while (true) {
          const { value, done } = await state.reader.read();
          if (done) break;
          state.buffer += decoder.decode(value, { stream: true });
        }
      } catch (e) {
        // reader fail propagates from writer error. We retry in feedBinaryFrame.
      }
    })();
    return state;
  }

  function ensureInflater(wsId, format) {
    if (inflaters.has(wsId)) return inflaters.get(wsId);
    const state = makeInflater(wsId, format);
    if (!state) return null;
    inflaters.set(wsId, state);
    usDebug.inflater_count = inflaters.size;
    return state;
  }

  // Buffer per-WS frames so we can retry with a different format if the
  // first attempt fails. Limit to a small replay buffer to bound memory.
  const replay_buffers = new Map(); // wsId -> Uint8Array[]

  async function feedBinaryFrame(wsId, ab) {
    const u8 = new Uint8Array(ab);
    const isFinal = endsWithSyncMarker(u8);

    // Capture first8 of the very first frame for diagnostic.
    if (!usDebug.ws_first_frames[wsId]) {
      const n = Math.min(8, u8.length);
      usDebug.ws_first_frames[wsId] = Array.from(u8.slice(0, n))
        .map(b => b.toString(16).padStart(2, "0")).join(" ");
    }

    let state = ensureInflater(wsId);
    if (!state) return;

    // Stash for potential replay on format change.
    if (!replay_buffers.has(wsId)) replay_buffers.set(wsId, []);
    const replay = replay_buffers.get(wsId);
    if (replay.length < 8) replay.push(u8);  // bounded

    try {
      await state.writer.write(u8);
    } catch (e) {
      usDebug.inflate_pako_err++;
      usDebug.last_pako_err = "[" + state.format + "] " + e.message;

      // Try the other format if we haven't already.
      const tried = new Set(state.tried_formats);
      const next = tried.has("deflate-raw") ? null : "deflate-raw";
      inflaters.delete(wsId);
      if (!next) {
        warn("inflate failed for both formats:", e.message);
        usDebug.inflater_count = inflaters.size;
        replay_buffers.delete(wsId);
        return;
      }
      warn("inflate failed for", state.format, "-- retrying with", next);
      const newState = makeInflater(wsId, next);
      if (!newState) {
        usDebug.inflater_count = inflaters.size;
        return;
      }
      newState.tried_formats = [...tried, next];
      inflaters.set(wsId, newState);
      usDebug.inflater_count = inflaters.size;
      // Replay buffered frames into the new inflater.
      for (const buf of replay) {
        try { await newState.writer.write(buf); }
        catch (e2) {
          warn("replay also failed:", e2.message);
          inflaters.delete(wsId);
          usDebug.inflater_count = inflaters.size;
          return;
        }
      }
      state = newState;
    }

    if (isFinal) {
      // Give the reader's microtask a chance to flush.
      await new Promise((r) => setTimeout(r, 0));
      if (!state.buffer) return;
      const { objects, remainder } = extractJsonObjects(state.buffer);
      state.buffer = remainder;
      if (objects.length === 0) return;
      usDebug.inflate_finals++;
      for (const objText of objects) {
        try {
          const payload = JSON.parse(objText);
          usDebug.inflate_json_ok++;
          handleGatewayMessage(payload);
        } catch (e) {
          warn("inflated JSON parse failed:", e.message, objText.slice(0, 100));
        }
      }
    }
  }

  document.addEventListener(BRIDGE_EVENT_NAME, (event) => {
    const data = event.detail;
    if (!data) return;

    if (data.__bnet_type === BRIDGE_MSG_TYPE) {
      usDebug.bridge_msg_received++;
      if (data.event === "connect") {
        stats.gateway_connections++;
        log("gateway tap intercepted connect:", data.url);
      } else if (data.event === "message") {
        try { handleGatewayMessage(data.payload); }
        catch (e) { warn("handleGatewayMessage threw:", e.message); }
      }
    } else if (data.__bnet_type === BRIDGE_BINARY_TYPE) {
      usDebug.bridge_bin_received++;
      if (data.event === "open") {
        log("gateway WS open (compressed):", data.wsId, data.url);
        inflaters.delete(data.wsId);
        usDebug.inflater_count = inflaters.size;
      } else if (data.event === "binary" && data.buffer) {
        try { feedBinaryFrame(data.wsId, data.buffer); }
        catch (e) { warn("feedBinaryFrame threw:", e.message); }
      }
    }
  });

  log("gateway tap injected; awaiting Discord bundle to create gateway WS");

  // ============================================================================
  // Action poller (still HTTP-based; bnetswitch posts actions for us)
  // ============================================================================

  async function executeAction(action) {
    log("executing action", action.id, action.type);
    try {
      switch (action.type) {
        case "join_by_message": {
          await joinByMessage(action);
          break;
        }
        case "set_nickname": {
          const urlMatch = window.location.pathname.match(/^\/channels\/(\d+)/);
          const currentGuild = urlMatch ? urlMatch[1] : null;
          if (currentGuild !== action.guild_id) {
            throw new Error(
              `wrong guild in view (current=${currentGuild || "none"}, ` +
                `wanted=${action.guild_id}); switch tabs and try again`
            );
          }
          await setServerNickname(action.nickname);
          break;
        }
        case "leave_voice": {
          const btn = document.querySelector('[aria-label="Disconnect"]');
          if (!btn) throw new Error("disconnect button not found (not in a VC?)");
          btn.click();
          break;
        }
        default:
          throw new Error("unknown action type: " + action.type);
      }
      await bnetRequest("POST", "/actions/ack", { id: action.id, success: true });
    } catch (e) {
      warn("action failed:", action.id, e.message);
      await bnetRequest("POST", "/actions/ack", {
        id: action.id,
        success: false,
        error: e.message,
      }).catch(() => {});
    }
  }

  async function joinByMessage(action) {
    // PRIMARY: send op 4 (Voice State Update) over the gateway WS. This
    // is exactly what the LFG embed's blue channel-mention link does
    // when you click it -- Discord's bundle picks up the resulting
    // VOICE_STATE_UPDATE event, sets up WebRTC, and you're actually in
    // the call. Just navigating to the channel URL (pushState or anchor
    // click) only switches view; it doesn't auto-join.
    if (action.guild_id && action.voice_channel_id) {
      log("joining via gateway op 4 (voice state update):",
        action.guild_id, "->", action.voice_channel_id);
      document.dispatchEvent(new CustomEvent("__bnetswitch_voice_state__", {
        detail: {
          guild_id: action.guild_id,
          channel_id: action.voice_channel_id,
          self_mute: false,
          self_deaf: false,
        },
      }));
      // Also navigate so the user sees the call view in their tab.
      const path = action.voice_channel_url
        ? new URL(action.voice_channel_url).pathname
        : `/channels/${action.guild_id}/${action.voice_channel_id}`;
      window.history.pushState(null, "", path);
      window.dispatchEvent(new PopStateEvent("popstate"));
      return;
    }

    // Fallback (no guild + channel ids): just navigate to whatever URL
    // we have, won't auto-join but at least gets the user there.
    if (action.voice_channel_url) {
      const path = new URL(action.voice_channel_url).pathname;
      log("joining via captured URL (no guild_id, navigation only):", path);
      window.history.pushState(null, "", path);
      window.dispatchEvent(new PopStateEvent("popstate"));
      return;
    }

    throw new Error(
      "no guild_id + voice_channel_id in action -- can't send op 4"
    );
  }

  async function pollActions() {
    try {
      const actions = await bnetRequest("GET", "/actions");
      if (Array.isArray(actions)) {
        for (const a of actions) await executeAction(a);
      }
    } catch (e) {
      if (!e.message.includes("network error")) debug("poll error:", e.message);
    }
  }

  // Poll bnetswitch's /health periodically. If the boot_id changes,
  // bnetswitch was restarted -- its in-memory state is wiped, so we
  // need to re-backfill the LFG channel history. Uses bnetRequest
  // (GM_xmlhttpRequest) so localhost CORS isn't a problem.
  let __bnet_last_boot_id = null;
  async function pollBootId() {
    try {
      const body = await bnetRequest("GET", "/health");
      const boot = body && body.boot_id;
      if (!boot) return;
      if (__bnet_last_boot_id === null) {
        __bnet_last_boot_id = boot;
        return;
      }
      if (boot !== __bnet_last_boot_id) {
        log("bnetswitch restarted (boot_id changed); re-backfilling LFG history");
        __bnet_last_boot_id = boot;
        __bnet_backfilled_channels.clear();
        __bnet_backfill_in_progress = false;
        scheduleBackfill();
      }
    } catch (e) {
      // Ignore network errors -- bnetswitch may be temporarily down.
    }
  }

  // ============================================================================
  // History backfill: fetch the last N messages from each watched channel
  // via Discord REST so the LFG view is populated immediately on startup
  // (the gateway tap is real-time-only and won't replay history).
  // Re-run on each fresh auth token capture to handle reconnects.
  // ============================================================================
  let __bnet_auth_token = null;
  let __bnet_backfill_in_progress = false;
  const __bnet_backfilled_channels = new Set();

  document.addEventListener("__bnetswitch_auth_captured__", (event) => {
    const token = event.detail?.token;
    if (!token) return;
    const fresh = token !== __bnet_auth_token;
    __bnet_auth_token = token;
    if (fresh) {
      log("captured Discord auth token (source=" + (event.detail.source || "?") + "); scheduling backfill");
      scheduleBackfill();
    }
  });

  function scheduleBackfill() {
    if (__bnet_backfill_in_progress) return;
    __bnet_backfill_in_progress = true;
    let attempts = 0;
    const tryBackfill = async () => {
      attempts++;
      if (attempts > 60) {
        warn("backfill: gave up after 60 attempts (gateway never ready?)");
        __bnet_backfill_in_progress = false;
        return;
      }
      // Wait for both auth token AND gateway to know about each watched channel.
      const allKnown = WATCHED_CHANNEL_IDS.every((cid) => GW.channels.has(cid));
      if (!__bnet_auth_token || !allKnown) {
        setTimeout(tryBackfill, 1000);
        return;
      }
      try {
        await backfillRecentMessages();
      } catch (e) {
        warn("backfill failed:", e.message);
      } finally {
        __bnet_backfill_in_progress = false;
      }
    };
    tryBackfill();
  }

  async function backfillRecentMessages() {
    for (const channelId of WATCHED_CHANNEL_IDS) {
      if (__bnet_backfilled_channels.has(channelId)) {
        debug("backfill: skipping already-backfilled channel", channelId);
        continue;
      }
      const ch = GW.channels.get(channelId);
      if (!ch) {
        warn("backfill: no channel info for", channelId);
        continue;
      }
      try {
        const url = "/api/v9/channels/" + channelId + "/messages?limit=50";
        const res = await fetch(url, {
          method: "GET",
          headers: { authorization: __bnet_auth_token, accept: "*/*" },
          credentials: "include",
        });
        if (!res.ok) {
          warn("backfill fetch", channelId, "failed:", res.status);
          continue;
        }
        const messages = await res.json();
        // Replay oldest -> newest so LfgState's front-insert ends up
        // newest-at-front, matching the real-time gateway flow.
        messages.reverse();
        let lfgFound = 0;
        for (const msg of messages) {
          // Re-shape to gateway dispatch format and reuse the existing
          // shouldProcessLfgMessage + postLfgMessage pipeline.
          try {
            handleGatewayMessage({
              op: 0,
              t: "MESSAGE_CREATE",
              s: 0,
              d: { ...msg, guild_id: msg.guild_id || ch.guild_id },
            });
            const username = msg.author?.username || msg.author?.global_name;
            if (username === LFG_BOT_USERNAME && msg.embeds?.length) lfgFound++;
          } catch (e) {
            warn("backfill: failed to process message:", e.message);
          }
        }
        log("backfill", channelId, ":", messages.length, "msgs (", lfgFound, "LFG)");
        __bnet_backfilled_channels.add(channelId);
      } catch (e) {
        warn("backfill error for", channelId, ":", e.message);
      }
    }
  }

  // ============================================================================
  // Voice status reporting (read from gateway state, no DOM needed)
  // ============================================================================
  async function reportVoiceStatus() {
    if (!GW.meId) return;
    const myVC = GW.userVoiceChannel.get(GW.meId);
    const ch = myVC ? GW.channels.get(myVC) : null;
    try {
      await bnetRequest("POST", "/status", {
        in_voice: !!myVC,
        voice_channel_id: myVC || null,
        voice_channel_name: ch?.name || null,
      });
    } catch (e) {}
  }

  // ============================================================================
  // Nickname change UI walk (still DOM-based; Discord doesn't expose
  // self-rename through gateway from the user's side -- it's a REST PATCH)
  // ============================================================================

  async function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function setReactInputValue(input, value) {
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value"
    ).set;
    nativeSetter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function findNicknameInput() {
    const isWrongInput = (el) =>
      !el ||
      el.type === "file" ||
      el.getAttribute("aria-label") === "Search" ||
      el.getAttribute("role") === "combobox" ||
      (el.className || "").toString().includes("hiddenVisually") ||
      (el.className || "").toString().includes("comboBoxInput");

    const allEls = document.querySelectorAll(
      'h1, h2, h3, h4, [class*="title_"], [class*="formText"]'
    );
    for (const h of allEls) {
      if ((h.textContent || "").trim() !== "Server Nickname") continue;
      let el = h.nextElementSibling;
      for (let depth = 0; depth < 6 && el; depth++) {
        const candidate = el.querySelector?.('input[type="text"], input:not([type])');
        if (candidate && !isWrongInput(candidate)) return candidate;
        el = el.nextElementSibling;
      }
    }
    return null;
  }

  /** Close any Discord modal that might be open. Used in finally to
   *  ensure we never leave the UI stuck after a failed nickname op.
   *  Safe to call when no modal is open (no-op).
   */
  function closeAnyModal() {
    const closeBtn = document.querySelector('button[aria-label="Close"]');
    if (closeBtn) {
      closeBtn.click();
      return;
    }
    document.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Escape",
        code: "Escape",
        bubbles: true,
        keyCode: 27,
        which: 27,
      })
    );
  }

  async function setServerNickname(nickname) {
    log("setServerNickname:", JSON.stringify(nickname));

    const dropdown = document.querySelector('[aria-label*="server actions"]');
    if (!dropdown) throw new Error("server-actions dropdown not found");

    try {
      dropdown.click();
      await sleep(150);

      const editProfile = document.getElementById(
        "guild-header-popout-change-nickname"
      );
      if (!editProfile) {
        document.body.click();
        throw new Error('"Edit Per-server Profile" menu item not found');
      }
      editProfile.click();

      let input = null;
      for (let i = 0; i < 30; i++) {
        await sleep(100);
        input = findNicknameInput();
        if (input) break;
      }
      if (!input) throw new Error("nickname input never appeared");

      // Short-circuit: the nickname is already set to the desired value.
      // Setting the input to the same value won't trigger React's change
      // detection -- Discord's "Save Changes" bar won't appear. Detect
      // and skip cleanly.
      const desired = (nickname || "").trim();
      const current = (input.value || "").trim();
      if (current === desired) {
        log("nickname already set to", JSON.stringify(desired), "-- no-op, closing modal");
        return; // fall through to finally -> closeAnyModal
      }

      input.focus();
      setReactInputValue(input, desired);
      await sleep(600);

      const targetText = desired.length > 0 ? "Save Changes" : "Reset";
      let button = null;
      for (let i = 0; i < 20; i++) {
        button = Array.from(document.querySelectorAll("button")).find(
          (b) => (b.textContent || "").trim() === targetText
        );
        if (button) break;
        await sleep(100);
      }
      if (!button) {
        // The save bar never appeared even after typing. This usually
        // means Discord didn't register the value change. Throw with
        // diagnostics so the user knows what to investigate.
        throw new Error(
          `"${targetText}" button not found after 2s ` +
            `(current="${current}", desired="${desired}")`
        );
      }
      button.click();

      await sleep(800);
    } finally {
      // ALWAYS close the modal, whether we succeeded, no-op'd, or
      // threw. Otherwise the Discord modal stays open and blocks the
      // user from interacting with other channels / messages.
      closeAnyModal();
    }
  }

  // ============================================================================
  // Bootstrap
  //
  // Most of the work happens in handleGatewayMessage which is wired up by
  // patchWebSocket() above (already running). The only post-DOM work is
  // setting up the action poller and voice status reporter.
  // ============================================================================

  function start() {
    log("bnetswitch LFG bridge starting (v0.9.1, op 14 lazy-guild voice subscribe)");
    log("server:", BNETSWITCH_HOST);
    log("watched channels:", WATCHED_CHANNEL_IDS.join(", ") || "all");

    bnetRequest("GET", "/health")
      .then(() => log("bnetswitch reachable"))
      .catch((e) =>
        warn("bnetswitch not reachable yet:", e.message, "(will keep trying)")
      );

    setInterval(pollActions, ACTION_POLL_INTERVAL_MS);
    setInterval(reportVoiceStatus, 5000);
    // Poll boot_id every 5s so we re-backfill within 5s of bnetswitch
    // restart. Initial call seeds __bnet_last_boot_id without action.
    pollBootId();
    setInterval(pollBootId, 5000);
    // Multi-browser leader election: register this session at boot
    // and re-register periodically (and on visibility change) so the
    // most-recently-active tab keeps "primary" status. Other tabs
    // remain useful for ingestion + backfill but don't execute joins.
    registerSession();
    setInterval(registerSession, SESSION_REGISTER_INTERVAL_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") registerSession();
    });
  }

  async function registerSession() {
    try {
      const res = await bnetRequest("POST", "/register", {
        session_id: SESSION_ID,
        user_agent: navigator.userAgent || "",
      });
      if (res && typeof res === "object") {
        const wasPrimary = window.__bnet_is_primary;
        window.__bnet_is_primary = !!res.is_primary;
        if (wasPrimary !== window.__bnet_is_primary) {
          log(
            "session " + SESSION_ID.slice(0, 8) +
              " is " + (res.is_primary ? "PRIMARY" : "secondary") +
              " (" + (res.session_count || 0) + " active)"
          );
        }
      }
    } catch (e) {
      debug("register failed:", e.message);
    }
  }

  // Wait for DOM to be interactable before setting up the action poller.
  // The gateway tap is already running -- it doesn't need DOM at all.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
