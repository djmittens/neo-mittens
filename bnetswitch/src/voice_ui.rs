use crate::{
    term_caps::{GraphicsProto, TermCaps},
    voice::{Event, Flags, Snapshot},
};
use ratatui::{
    layout::Rect,
    style::{Color, Modifier, Style},
    text::Line,
    widgets::{Block, Borders, Paragraph, Wrap},
    Frame,
};
use ratatui_image::{
    picker::{Picker, ProtocolType},
    protocol::Protocol,
    Image, Resize,
};
use std::collections::HashMap;

#[derive(Default)]
pub struct VoicePanel {
    pub focused: bool,
    pub history: bool,
    pub selected: Option<String>,
    pub channel: Option<String>,
    picker: Option<Picker>,
    images: HashMap<String, Protocol>,
    history_scroll: u16,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::voice::Member;
    #[test]
    fn sidebar_renders_identity_flags_and_speaker_and_keeps_departed_selection() {
        let mut terminal =
            ratatui::Terminal::new(ratatui::backend::TestBackend::new(60, 24)).unwrap();
        let mut panel = VoicePanel::default();
        let mut snapshot = Snapshot {
            channel_id: Some("vc".into()),
            observed_at_ms: 2000,
            members: vec![Member {
                user_id: "123456789012345678".into(),
                nickname: "Server Nick".into(),
                speaking: true,
                joined_at_ms: 1000,
                ..Member::default()
            }],
            ..Snapshot::default()
        };
        let flags = [(
            "123456789012345678".into(),
            Flags {
                banned_me: true,
                ..Flags::default()
            },
        )]
        .into_iter()
        .collect();
        let caps = TermCaps {
            graphics: GraphicsProto::None,
            in_tmux: false,
            has_tty: false,
        };
        terminal
            .draw(|f| panel.render(f, f.area(), &snapshot, &flags, &[], None, &caps, 2000))
            .unwrap();
        let buf = terminal.backend().buffer();
        let text: String = buf.content.iter().map(|cell| cell.symbol()).collect();
        assert!(text.contains("Server Nick"));
        assert!(text.contains("(123456789012345678)"));
        assert!(text.contains("BANNED ME"));
        assert!(buf
            .content
            .iter()
            .any(|cell| cell.symbol() == "●" && cell.fg == Color::Green));
        snapshot.members = vec![Member {
            user_id: "someone-else".into(),
            nickname: "New".into(),
            ..Member::default()
        }];
        terminal
            .draw(|f| panel.render(f, f.area(), &snapshot, &flags, &[], None, &caps, 2000))
            .unwrap();
        assert_eq!(panel.selected.as_deref(), Some("123456789012345678"));
    }
}

impl VoicePanel {
    pub fn navigate(&mut self, snapshot: &Snapshot, delta: i32) {
        if self.history {
            self.history_scroll = (i32::from(self.history_scroll) + delta * 3).clamp(0, 87) as u16;
            return;
        }
        if snapshot.members.is_empty() {
            return;
        }
        let index = self
            .selected
            .as_ref()
            .and_then(|id| snapshot.members.iter().position(|m| &m.user_id == id));
        let next = index
            .map(|i| (i as i32 + delta).rem_euclid(snapshot.members.len() as i32) as usize)
            .unwrap_or(0);
        self.selected = Some(snapshot.members[next].user_id.clone());
    }

    pub fn render(
        &mut self,
        f: &mut Frame,
        area: Rect,
        snapshot: &Snapshot,
        flags: &std::collections::BTreeMap<String, Flags>,
        events: &[Event],
        error: Option<&str>,
        caps: &TermCaps,
        now: u64,
    ) {
        if self.channel != snapshot.channel_id {
            self.channel = snapshot.channel_id.clone();
            self.selected = snapshot
                .members
                .iter()
                .find(|m| m.user_id != snapshot.me_id)
                .map(|m| m.user_id.clone());
            self.images.clear();
        }
        let stale = now.saturating_sub(snapshot.observed_at_ms) > 60_000;
        let title = format!(
            " Voice{}{} ",
            if self.focused { " [focused]" } else { "" },
            if stale { " [STALE]" } else { "" }
        );
        let block = Block::default()
            .borders(Borders::ALL)
            .title(title)
            .border_style(Style::default().fg(if self.focused {
                Color::Cyan
            } else {
                Color::Gray
            }));
        let inner = block.inner(area);
        f.render_widget(block, area);
        if inner.width < 8 || inner.height < 4 {
            return;
        }
        if self.history {
            let lines: Vec<Line> = events
                .iter()
                .rev()
                .take(30)
                .flat_map(|e| {
                    vec![
                        Line::from(format!(
                            "{} {} {}",
                            e.timestamp_ms,
                            e.kind,
                            e.user_id.as_deref().unwrap_or("")
                        )),
                        Line::from(format!(
                            "actor={} owner={}{}",
                            e.actor_id.as_deref().unwrap_or("unknown"),
                            e.owner_id.as_deref().unwrap_or("unknown"),
                            e.duration_ms
                                .map(|d| format!(" {}s", d / 1000))
                                .unwrap_or_default()
                        )),
                        Line::from(e.evidence.clone()),
                    ]
                })
                .collect();
            f.render_widget(
                Paragraph::new(lines)
                    .wrap(Wrap { trim: false })
                    .scroll((self.history_scroll, 0)),
                inner,
            );
            return;
        }
        let header = format!(
            "{}\nOwner: {}\nTab focus · j/k select\nb ban · c claim · t flag · h history",
            snapshot.channel_name.as_deref().unwrap_or("Not in voice"),
            snapshot.owner_id.as_deref().unwrap_or("unknown")
        );
        f.render_widget(
            Paragraph::new(header).wrap(Wrap { trim: false }),
            Rect::new(inner.x, inner.y, inner.width, 5.min(inner.height)),
        );
        let available = inner.height.saturating_sub(7) / 4;
        let selected_index = self
            .selected
            .as_ref()
            .and_then(|id| snapshot.members.iter().position(|m| &m.user_id == id))
            .unwrap_or(0);
        let offset = selected_index.saturating_sub(available.saturating_sub(1) as usize);
        for (row, member) in snapshot
            .members
            .iter()
            .skip(offset)
            .take(available as usize)
            .enumerate()
        {
            let y = inner.y + 5 + row as u16 * 4;
            let selected = self.selected.as_deref() == Some(&member.user_id);
            let mark = flags.get(&member.user_id).cloned().unwrap_or_default();
            let tags = [
                mark.banned_by_me.then_some("BANNED BY ME"),
                (mark.ban_requested && !mark.banned_by_me).then_some("BAN REQUESTED?"),
                mark.banned_me.then_some("BANNED ME"),
                mark.troll.then_some("TROLL"),
            ]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>()
            .join(" · ");
            let style = Style::default()
                .fg(if member.speaking && !stale {
                    Color::Green
                } else if !tags.is_empty() {
                    Color::LightRed
                } else {
                    Color::White
                })
                .bg(if selected {
                    Color::DarkGray
                } else {
                    Color::Reset
                })
                .add_modifier(if member.speaking && !stale {
                    Modifier::BOLD
                } else {
                    Modifier::empty()
                });
            let elapsed = now
                .min(if stale { snapshot.observed_at_ms } else { now })
                .saturating_sub(member.joined_at_ms)
                / 1000;
            let text = format!(
                "{}{}{}\n({})\n{}m {:02}s {}",
                if selected { "> " } else { "  " },
                if member.speaking && !stale {
                    "● "
                } else {
                    ""
                },
                member.nickname,
                member.user_id,
                elapsed / 60,
                elapsed % 60,
                tags
            );
            f.render_widget(
                Paragraph::new(text).style(style),
                Rect::new(inner.x + 5, y, inner.width.saturating_sub(5), 3),
            );
            let image_area = Rect::new(inner.x, y, 4, 2);
            f.render_widget(Paragraph::new(" ◉").style(style), image_area);
            if caps.supports_images() {
                if self.picker.is_none() {
                    let mut picker = Picker::from_fontsize(crate::rank_icons::detect_font_size());
                    picker.set_protocol_type(match caps.graphics {
                        GraphicsProto::Kitty => ProtocolType::Kitty,
                        GraphicsProto::Sixel => ProtocolType::Sixel,
                        GraphicsProto::ITerm2 => ProtocolType::Iterm2,
                        GraphicsProto::None => ProtocolType::Halfblocks,
                    });
                    self.picker = Some(picker);
                }
                if let Some(url) = &member.avatar_url {
                    if !self.images.contains_key(url) {
                        if let Ok(path) = crate::voice::avatar_path(url) {
                            if let Ok(bytes) = std::fs::read(path) {
                                if let Ok(img) = image::load_from_memory(&bytes) {
                                    if let Ok(protocol) = self
                                        .picker
                                        .as_mut()
                                        .unwrap()
                                        .new_protocol(img, image_area, Resize::Fit(None))
                                    {
                                        self.images.insert(url.clone(), protocol);
                                    }
                                }
                            }
                        }
                    }
                    if let Some(protocol) = self.images.get(url) {
                        f.render_widget(Image::new(protocol), image_area);
                    }
                }
            }
        }
        let footer = error.unwrap_or(if stale {
            "Bridge offline — durations stopped"
        } else {
            "Actor unknown unless bot identifies them"
        });
        f.render_widget(
            Paragraph::new(footer)
                .style(Style::default().fg(Color::Yellow))
                .wrap(Wrap { trim: false }),
            Rect::new(inner.x, inner.bottom().saturating_sub(2), inner.width, 2),
        );
    }
}
