// Run with: node --test userscripts/bnetswitch-voice.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const guild = '94882524378968064';
const me = '111111111111111111';
const other = '222222222222222222';
const vc = '333333333333333333';

function harness({ injectPage = false, modules = {}, fetchHandler = null } = {}) {
  const requests = [];
  const discordRequests = [];
  const domEvents = [];
  const listeners = new Map();
  const document = {
    readyState: 'loading', documentElement: {}, head: {}, body: null,
    addEventListener(type, listener) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(listener); },
    dispatchEvent(event) { domEvents.push(event); for (const listener of listeners.get(event.type) || []) listener(event); },
    getElementById() { return null; },
    querySelectorAll() { return []; }, querySelector() { return null; },
  };
  const window = { addEventListener() {}, dispatchEvent() {}, location: { pathname: `/channels/${guild}/1192075868609183754` } };
  class Socket { addEventListener() {} send() {} }
  class XHR { setRequestHeader() {} }
  window.WebSocket = Socket;
  window.webpackChunkdiscord_app = [];
  window.webpackChunkdiscord_app.push = (entry) => { Array.prototype.push.call(window.webpackChunkdiscord_app, entry); entry[2]({ c: modules }); };
  const context = vm.createContext({
    document, window, unsafeWindow: window, location: window.location,
    navigator: { userAgent: 'test' }, crypto: { randomUUID: () => 'test-session' }, console, TextDecoder,
    MutationObserver: class { observe() {} },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    Event: class {}, PopStateEvent: class {}, WebSocket: Socket, XMLHttpRequest: XHR, Headers,
    GM_log() {}, GM_getValue: (_, fallback) => fallback, GM_setValue() {},
    GM_addElement: (type, options) => { if (injectPage && type === 'script') vm.runInContext(options.textContent, context); return { remove() {} }; },
    fetch: async (url, init) => { discordRequests.push(url); return fetchHandler ? fetchHandler(url, init) : { ok: true, json: async () => ({ id: me, username: 'My user' }) }; },
    GM_xmlhttpRequest(request) {
      requests.push({ path: new URL(request.url).pathname, body: request.data ? JSON.parse(request.data) : null });
      request.onload({ status: 200, responseText: '{"ok":true}' });
    },
    // Debounce timers stay paused; sleep timers resolve immediately.
    setTimeout: (fn, ms) => { if (ms === 100) fn(); return 1; }, clearTimeout() {}, setInterval() {}, clearInterval() {},
  });
  window.fetch = (...args) => context.fetch(...args);
  let source = fs.readFileSync(`${__dirname}/bnetswitch-lfg.user.js`, 'utf8');
  const end = source.lastIndexOf('})();');
  source = source.slice(0, end) + 'window.testVoice = { GW, handleGatewayMessage, voiceSnapshot, moderateVoiceViaInterface, recoverCurrentUser, hydrateVoiceRoster, applyVoiceRoster, subscribeToGuildVoice };\n' + source.slice(end);
  vm.runInContext(source, context);
  const api = window.testVoice;
  api.GW.meId = me;
  api.GW.channels.set(vc, { guild_id: guild, name: 'Stack' });
  api.GW.userVoiceChannel.set(me, vc);
  api.GW.voiceStates.set(vc, new Set([me, other]));
  return { api, requests, discordRequests, document, window, domEvents };
}

test('voice membership and guild nicknames update from batched gateway events', () => {
  const { api } = harness();
  api.handleGatewayMessage({ op: 0, t: 'VOICE_STATE_UPDATE_BATCH', d: { voice_states: [{ guild_id: guild, user_id: other, channel_id: vc,
    member: { user: { id: other, username: 'username', global_name: 'Global', avatar: 'abc' }, nick: 'Server Nick' } }] } });
  api.handleGatewayMessage({ op: 0, t: 'GUILD_MEMBER_UPDATE', d: { guild_id: 'different', user: { id: other, username: 'username' }, nick: 'Wrong server' } });
  let member = api.voiceSnapshot().members.find((m) => m.user_id === other);
  assert.equal(member.nickname, 'Server Nick');
  assert.match(member.avatar_url, /abc\.png/);
  api.handleGatewayMessage({ op: 0, t: 'GUILD_MEMBER_UPDATE', d: { guild_id: guild, user: { id: other }, nick: null } });
  assert.equal(api.voiceSnapshot().members.find((m) => m.user_id === other).nickname, 'Global');
  api.handleGatewayMessage({ op: 0, t: 'VOICE_STATE_UPDATE', d: { user_id: other, channel_id: null } });
  assert.equal(api.voiceSnapshot().members.length, 1);
});

test('explicit bot evidence identifies a banner; disconnects do not', () => {
  const { api, requests } = harness();
  const message = { id: 'message-1', guild_id: guild, channel_id: 'interface', author: { bot: true }, content: `<@${other}> banned <@${me}> from <#${vc}>` };
  api.handleGatewayMessage({ op: 0, t: 'MESSAGE_CREATE', d: message });
  const event = requests.find((r) => r.path === '/voice/evidence').body;
  assert.equal(event.actor_id, other);
  assert.equal(event.user_id, me);
  assert.equal(event.kind, 'ban');
  requests.length = 0;
  api.handleGatewayMessage({ op: 0, t: 'VOICE_STATE_UPDATE', d: { user_id: me, channel_id: null } });
  api.handleGatewayMessage({ op: 0, t: 'MESSAGE_CREATE', d: { ...message, author: { bot: false } } });
  assert.equal(requests.filter((r) => r.path === '/voice/evidence').length, 0);
});

test('connect denial records unknown actor, not channel owner', () => {
  const { api, requests } = harness();
  for (const overwrites of [[], [{ id: me, type: 1, deny: '1048576' }]]) {
    api.handleGatewayMessage({ op: 0, t: 'CHANNEL_UPDATE', d: { id: vc, guild_id: guild, permission_overwrites: overwrites } });
  }
  const event = requests.find((r) => r.path === '/voice/evidence').body;
  assert.equal(event.kind, 'connect_denied');
  assert.equal(event.actor_id, null);
});

function backgroundHarness({ operation = 'ban', selectType = 3, options = null, onButton = null, rejectStatus = null, actor = me, gatewayFailure = false, emitDropdown = true } = {}) {
  const channel = '1192075868609183754';
  const app = '666666666666666666';
  const source = { id: '555555555555555555', channel_id: channel, guild_id: guild,
    application_id: app, author: { id: app, bot: true }, components: [{ type: 1, components: [{ type: 2, label: operation, custom_id: `actual-${operation}-button` }] }] };
  const posts = [];
  let api;
  const h = harness({ fetchHandler: async (url, init) => {
    if (url.includes('/messages?')) return { ok: true, status: 200, json: async () => [source] };
    assert.equal(url, '/api/v9/interactions');
    const body = JSON.parse(init.body);
    posts.push(body);
    if (rejectStatus) return { ok: false, status: rejectStatus, json: async () => ({ message: 'No permission' }) };
    if (body.data.component_type === 2) {
      onButton?.(api);
      if (gatewayFailure) api.handleGatewayMessage({ op: 0, t: 'INTERACTION_FAILURE', d: { nonce: body.nonce, reason_code: 1 } });
      const message = { id: String((BigInt(Date.now() - 1420070400000) << 22n) + 123n), channel_id: channel,
        guild_id: guild, application_id: app, author: source.author, flags: 64,
        interaction_metadata: { user: { id: actor }, interacted_message_id: source.id },
        components: [{ type: 1, components: [{ type: selectType, custom_id: 'actual-dynamic-dropdown',
          options: options || [{ label: 'Duplicate nickname', value: me }, { label: 'Duplicate nickname', value: other }] }] }] };
      if (emitDropdown) api.handleGatewayMessage({ op: 0, t: 'MESSAGE_CREATE', d: message });
    }
    return { ok: true, status: 204 };
  } });
  api = h.api;
  api.GW.discordSessionId = 'actual-discord-session';
  h.window.__bnet_auth_token = 'test-token';
  h.window.location.pathname = `/channels/${guild}/182420486582435840`;
  h.document.querySelectorAll = () => { throw new Error('background moderation must not inspect/click DOM controls'); };
  return { ...h, posts };
}

test('background ban submits real components and exact ID without navigating or clicking DOM', async () => {
  const { api, posts, requests, window } = backgroundHarness();
  const path = window.location.pathname;
  await api.moderateVoiceViaInterface({ id: 'act-1', channel_id: vc, user_id: other, operation: 'ban' });
  assert.equal(posts.length, 2);
  assert.equal(posts[0].data.custom_id, 'actual-ban-button');
  assert.equal(posts[1].data.custom_id, 'actual-dynamic-dropdown');
  assert.deepEqual(posts[1].data.values, [other]);
  assert.equal(posts[1].session_id, 'actual-discord-session');
  assert.notEqual(posts[0].nonce, posts[1].nonce);
  assert.equal(posts[1].message_flags, 64);
  assert.equal(window.location.pathname, path);
  assert.equal(requests.find((r) => r.body?.kind === 'ban_requested').body.actor_id, me);
});

test('background ban refuses departed targets and values without the selected Discord ID', async () => {
  const h = backgroundHarness({ options: [{ label: 'Duplicate nickname', value: 'somebody-else' }] });
  h.api.GW.voiceStates.get(vc).delete(other);
  await assert.rejects(h.api.moderateVoiceViaInterface({ id: 'act-2', channel_id: vc, user_id: other, operation: 'ban' }), /target left/);
  assert.equal(h.posts.length, 0);
  h.api.GW.voiceStates.get(vc).add(other);
  await assert.rejects(h.api.moderateVoiceViaInterface({ id: 'act-3', channel_id: vc, user_id: other, operation: 'ban' }), /Discord ID/);
  assert.equal(h.posts.length, 1, 'must not guess the dropdown value');
  assert.equal(h.requests.filter((r) => r.body?.kind === 'ban_requested').length, 0);
});

test('background claim selects the current voice channel without changing the chat view', async () => {
  const { api, posts, requests, window } = backgroundHarness({ operation: 'claim', selectType: 8 });
  const path = window.location.pathname;
  await api.moderateVoiceViaInterface({ id: 'claim-1', channel_id: vc, operation: 'claim' });
  assert.deepEqual(posts[1].data.values, [vc]);
  assert.equal(posts[1].data.component_type, 8);
  assert.equal(window.location.pathname, path);
  const event = requests.find((r) => r.body?.kind === 'claim_requested').body;
  assert.equal(event.user_id, me);
  assert.equal(event.actor_id, me);
});

test('background moderation does not select for another actor, retry rejected requests, or continue after target leaves', async () => {
  const wrongActor = backgroundHarness({ actor: '999999999999999999' });
  await assert.rejects(wrongActor.api.moderateVoiceViaInterface({ id: 'wrong-actor', channel_id: vc, user_id: other, operation: 'ban' }), /dropdown response/);
  assert.equal(wrongActor.posts.length, 1);
  const forbidden = backgroundHarness({ rejectStatus: 403 });
  await assert.rejects(forbidden.api.moderateVoiceViaInterface({ id: 'forbidden', channel_id: vc, user_id: other, operation: 'ban' }), /HTTP 403/);
  assert.equal(forbidden.posts.length, 1);
  const departed = backgroundHarness({ onButton: (api) => api.GW.voiceStates.get(vc).delete(other) });
  await assert.rejects(departed.api.moderateVoiceViaInterface({ id: 'departed', channel_id: vc, user_id: other, operation: 'ban' }), /target left/);
  assert.equal(departed.posts.length, 1);
  const failed = backgroundHarness({ gatewayFailure: true });
  await assert.rejects(failed.api.moderateVoiceViaInterface({ id: 'gateway-failed', channel_id: vc, user_id: other, operation: 'ban' }), /bot interaction failed/);
  assert.equal(failed.posts.length, 1);
});

test('background moderation reads a cached ephemeral response through the page-world bridge', async () => {
  const channel = '1192075868609183754';
  const app = '666666666666666666';
  const source = { id: '555555555555555555', channel_id: channel, author: { id: app, bot: true }, components: [{ type: 1, components: [{ type: 2, custom_id: 'button', label: 'Ban' }] }] };
  const messages = [];
  const posts = [];
  const { api, window } = harness({ injectPage: true, modules: {
    messages: { exports: { getMessage() {}, getMessages: () => ({ toArray: () => messages }) } },
    session: { exports: { getSessionId: () => 'native-client-session' } },
  }, fetchHandler: async (url, init) => {
    if (url.includes('/messages?')) return { ok: true, status: 200, json: async () => [source] };
    const body = JSON.parse(init.body); posts.push(body);
    if (body.data.component_type === 2) messages.push({
      id: String((BigInt(Date.now() - 1420070400000) << 22n) + 123n), channelId: channel, author: source.author,
      flags: 64, interactionMetadata: { user: { id: me }, interacted_message_id: source.id },
      components: [{ type: 1, components: [{ type: 5, customId: 'native-user-select' }] }],
    });
    return { ok: true, status: 204 };
  } });
  window.__bnet_auth_token = 'test-token';
  window.location.pathname = `/channels/${guild}/182420486582435840`;
  await api.moderateVoiceViaInterface({ id: 'native-response', channel_id: vc, user_id: other, operation: 'ban' });
  assert.equal(posts.length, 2);
  assert.equal(posts[1].data.custom_id, 'native-user-select');
  assert.deepEqual(posts[1].data.values, [other]);
  assert.equal(posts[1].session_id, 'native-client-session');
  assert.equal(window.location.pathname, `/channels/${guild}/182420486582435840`);
});

test('gateway resume supplies the real Discord session for background interactions', () => {
  const { window } = harness({ injectPage: true });
  const socket = new window.WebSocket('wss://gateway.discord.gg');
  socket.url = 'wss://gateway.discord.gg';
  socket.send(JSON.stringify({ op: 6, d: { session_id: 'resumed-session', token: 'not-exported' } }));
  assert.equal(window.__bnet_gateway_session_id, 'resumed-session');
});

test('missing session metadata and old dropdowns fail without UI movement or a guessed selection', async () => {
  const missing = backgroundHarness();
  missing.api.GW.discordSessionId = null;
  const path = missing.window.location.pathname;
  await assert.rejects(missing.api.moderateVoiceViaInterface({ id: 'no-session', channel_id: vc, user_id: other, operation: 'ban' }), /session ID unavailable/);
  assert.equal(missing.posts.length, 0);
  assert.equal(missing.window.location.pathname, path);
  const stale = backgroundHarness({ emitDropdown: false });
  stale.api.handleGatewayMessage({ op: 0, t: 'MESSAGE_CREATE', d: {
    id: String((BigInt(Date.now() - 1420070400000) << 22n) + 123n), channel_id: '1192075868609183754', guild_id: guild,
    author: { id: '666666666666666666', bot: true }, flags: 64,
    interaction_metadata: { user: { id: me }, interacted_message_id: '555555555555555555' },
    components: [{ type: 1, components: [{ type: 5, custom_id: 'old-dropdown' }] }],
  } });
  await assert.rejects(stale.api.moderateVoiceViaInterface({ id: 'old-response', channel_id: vc, user_id: other, operation: 'ban' }), /dropdown response/);
  assert.equal(stale.posts.length, 1);
  assert.equal(stale.window.location.pathname, path);
});

test('resume-only startup recovers self identity and uncached voice channel metadata', async () => {
  const { api, discordRequests, window } = harness();
  api.GW.meId = null;
  api.GW.channels.clear();
  api.GW.userVoiceChannel.clear();
  api.GW.voiceStates.clear();
  window.__bnet_auth_token = 'test-token';
  api.handleGatewayMessage({ op: 0, t: 'RESUMED', d: {} });
  // Before identity is recovered, absent READY must not mark voice as false.
  assert.equal(window.__bnet_self_in_voice, undefined);
  api.handleGatewayMessage({ op: 0, t: 'VOICE_STATE_UPDATE_BATCH', d: { guild_id: guild, voice_states: [
    { user_id: me, channel_id: vc }, { user_id: other, channel_id: vc },
  ] } });
  await api.recoverCurrentUser();
  const snapshot = api.voiceSnapshot();
  assert.equal(api.GW.ready, false);
  assert.equal(snapshot.me_id, me);
  assert.equal(snapshot.channel_id, vc);
  assert.equal(snapshot.guild_id, guild);
  assert.equal(snapshot.members.length, 2);
  assert.deepEqual(discordRequests, ['/api/v9/users/@me']);
  assert.equal(window.__bnet_self_in_voice, true);
});

test('rendered existing participants hydrate without join events; scrolling does not remove them', () => {
  const { api, document } = harness();
  api.GW.voiceStates.set(vc, new Set([me]));
  const row = {
    closest: () => null,
    getAttribute: (key) => key === 'data-list-item-id' ? `voiceuser-${vc}-${other}` : null,
    querySelector: (selector) => selector.includes('username') ? { textContent: 'Already in VC' } : { getAttribute: (key) => key === 'src' ? `https://cdn.discordapp.com/avatars/${other}/old.webp?size=64` : null },
    querySelectorAll: () => [],
  };
  document.querySelectorAll = (selector) => selector.includes(`voiceuser-${vc}-`) ? [row] : [];
  api.hydrateVoiceRoster();
  let snapshot = api.voiceSnapshot();
  assert.equal(snapshot.members.length, 2);
  assert.equal(snapshot.members.find((m) => m.user_id === other).nickname, 'Already in VC');
  assert.match(snapshot.members.find((m) => m.user_id === other).avatar_url, /old\.png/);
  document.querySelectorAll = () => [];
  api.hydrateVoiceRoster();
  assert.equal(api.voiceSnapshot().members.length, 2);
});

test('page-world Discord store hydrates members who predate the gateway tap', () => {
  const states = { [me]: { userId: me, channelId: vc }, [other]: { userId: other, channelId: vc } };
  const voiceStore = { getVoiceStatesForChannel: () => states };
  const userStore = { getCurrentUser: () => ({ id: me }), getUser: (id) => ({ id, username: id === other ? 'Other user' : 'Me', avatar: 'hash' }) };
  const memberStore = { getMembers() {}, getMember: (_, id) => ({ nick: id === other ? 'Server nickname' : 'My nickname' }) };
  const { api, domEvents, window } = harness({ injectPage: true, modules: {
    voice: { exports: { Z: voiceStore } }, users: { exports: { default: userStore } }, members: { exports: memberStore },
  } });
  api.GW.voiceStates.set(vc, new Set([me]));
  api.hydrateVoiceRoster();
  const snapshot = api.voiceSnapshot();
  assert.equal(snapshot.members.length, 2);
  assert.equal(snapshot.members.find((m) => m.user_id === other).nickname, 'Server nickname');
  assert.equal(window.bnetswitchVoiceDiagnose().hydration.source, 'discord_store');
  assert.equal(window.webpackChunkdiscord_app.length, 0, 'probe chunk should be removed');
  assert.ok(domEvents.some((e) => e.type === '__bnetswitch_voice_roster_snapshot__'));
  delete states[other];
  api.applyVoiceRoster({ channel_id: vc, source: 'discord_store', states: [{ user_id: me, channel_id: vc, guild_id: guild }] });
  assert.equal(api.voiceSnapshot().members.length, 1, 'authoritative snapshots can remove departed users');
});

test('later LFG subscriptions retain the joined voice channel range', () => {
  const { api, domEvents } = harness();
  const second = '444444444444444444';
  api.subscribeToGuildVoice(guild, vc);
  api.subscribeToGuildVoice(guild, second);
  const events = domEvents.filter((e) => e.type === '__bnetswitch_subscribe_guild__');
  assert.deepEqual(Object.keys(events.at(-1).detail.channels).sort(), [vc, second].sort());
});
