The strongest version of this idea is a multimodal computer-control system: gaze selects the target, hand gestures choose the action, and voice handles text entry. Keeping those responsibilities separate will make the interface more accurate and easier to learn.

# Product Requirements Document

## 1. Product overview

Working title: **Chudvis**

Chudvis enables hands-free or low-contact computer control through:

- Eye tracking for pointing and target selection
- Hand gestures for clicks, scrolling, zooming, navigation, and window control
- Voice recognition for text entry
- Visual and audio feedback to confirm recognized actions

The system should allow a user to complete common desktop tasks without relying on a mouse or keyboard.

## 2. Problem statement

Traditional computer input requires precise physical interaction with a mouse, trackpad, or keyboard. This can be difficult or impossible for:

- People with limited mobility
- Users recovering from an injury
- People working in sterile or hands-busy environments
- Users interacting with displays from a distance
- Anyone seeking a more natural or experimental form of computer interaction

Existing gaze-only interfaces can accidentally activate whatever the user looks at. Chudvis avoids this “Midas touch” problem by using gaze only to select a location and requiring a deliberate gesture to perform an action.

## 3. Product goals

The product should:

- Let users point anywhere on the screen using their eyes
- Perform common actions using a small, memorable gesture set
- Enter text through speech when a text field is selected
- Prevent unintended actions through confidence checks and confirmation feedback
- Support calibration for different users, cameras, lighting, and screen sizes
- Work with standard desktop applications when possible
- Provide an accessible alternative to conventional input devices

## 4. Non-goals for the first version

The initial product does not need to:

- Completely replace every keyboard shortcut
- Recognize sign language
- Interpret complex multi-hand gestures
- Work perfectly in poor lighting or with heavily obstructed faces
- Support multiple users simultaneously
- Understand unrestricted voice commands
- Control high-risk operations without confirmation

## 5. Core interaction model

Each interaction follows this sequence:

1. The user looks at a target.
2. The system estimates and stabilizes the gaze location.
3. A cursor or highlight shows the current target.
4. The user performs a gesture.
5. The system checks gesture and gaze confidence.
6. The action is executed at the stabilized gaze location.
7. Visual or audio feedback confirms the result.

For destructive actions such as closing a window, the system should require either a higher-confidence gesture, a brief confirmation, or an undo period.

## 6. Input responsibilities

| Input | Primary responsibility |
|---|---|
| Eyes | Select a screen position or interface element |
| Hand gestures | Choose and execute an action |
| Voice | Dictate text or issue a limited command |
| Visual feedback | Show gaze position, gesture status, and action result |
| Audio feedback | Confirm actions or report recognition problems |

## 7. Proposed gesture vocabulary

The first version should use as few gestures as possible.

| Gesture | Action |
|---|---|
| Quick pinch or finger tap | Primary click |
| Pinch and hold | Click and drag |
| Pinch hands/fingers together or apart | Zoom out or zoom in |
| Open-hand movement up/down | Scroll |
| Flick left/right | Back or forward |
| Flick upward | Open or launch selected item |
| Deliberate side flick with closed hand | Close current window |
| Open palm held briefly | Pause or cancel current action |
| Point and hold | Secondary click or context menu |
| Confirm gesture, such as thumb up | Submit, enter, or confirm |

Gesture meanings should remain consistent across applications. Users should also be able to remap them.

## 8. Gaze tracking requirements

The system should:

- Guide the user through an initial calibration
- Estimate the user’s screen-space gaze coordinates
- Smooth small involuntary eye movements
- Stabilize the selected target immediately before a gesture
- Snap to nearby clickable elements when confidence is high
- Display an optional gaze cursor or target highlight
- Detect when the user looks away from the screen
- Allow quick recalibration
- Report low tracking confidence instead of guessing

The action should use the gaze position captured near the beginning of the gesture—not necessarily where the user is looking after completing it. People often look toward the expected result while performing an action.

## 9. Gesture tracking requirements

The gesture subsystem should:

- Detect one or two hands through a standard camera
- Track hand landmarks and movement over time
- Distinguish deliberate gestures from ordinary movement
- Assign a confidence score to each recognized gesture
- Include cooldown periods to prevent duplicate actions
- Show when a gesture has been detected
- Let users pause gesture recognition
- Support left-handed and right-handed users
- Allow sensitivity and movement thresholds to be adjusted

## 10. Voice and text entry

When the user clicks a recognized text field:

1. The field receives focus.
2. Dictation mode begins automatically or after a microphone gesture.
3. Speech is converted into text.
4. Partial transcription is displayed as the user speaks.
5. Spoken punctuation such as “comma” or “new paragraph” is supported.
6. A confirmation gesture submits the text or presses Enter.
7. A cancel gesture stops dictation without submitting.
8. Voice capture ends when focus leaves the field.

Useful voice commands could include:

- “Delete last word”
- “Clear field”
- “New line”
- “Select all”
- “Undo”
- “Stop listening”

The system should visibly indicate whenever the microphone is active.

## 11. Functional requirements

### Cursor and selection

- Move an on-screen pointer based on gaze
- Highlight the likely interface target
- Perform primary and secondary clicks
- Double-click when explicitly requested
- Drag and drop using a hold gesture

### Navigation

- Scroll vertically and horizontally
- Move backward and forward
- Switch between open applications
- Open, minimize, maximize, and close windows
- Zoom in and out
- Confirm or cancel dialogs

### Text interaction

- Detect when a text field receives focus
- Start and stop dictation
- Insert recognized speech
- Apply basic editing commands
- Submit text through an Enter gesture

### System control

- Pause all recognition
- Recalibrate gaze tracking
- Adjust cursor smoothing and gesture sensitivity
- Display camera, microphone, and tracking status
- Provide an emergency stop method using a conventional input or dedicated gesture

## 12. Major use cases

### Accessibility

A user with limited hand mobility browses the web, opens applications, writes messages, and handles documents using gaze, minimal gestures, and voice.

### Hands-busy environments

A technician, cook, medical worker, or workshop user controls a computer without repeatedly touching input devices.

### Presentations and kiosks

A presenter controls slides, zooms into content, and opens media while standing away from the computer.

### Gaming and creative tools

Gaze selects objects while gestures manipulate them. This should be treated as a later extension because latency and precision requirements are higher.

### Smart displays and large screens

A user controls a television, public display, or wall-mounted dashboard from a distance.

## 13. User interface

The interface should include:

- A gaze cursor or subtle target highlight
- A gesture recognition indicator
- A microphone-active indicator
- A short action label, such as “Click,” “Scroll,” or “Close”
- A calibration screen
- A gesture tutorial and practice mode
- Sensitivity and accessibility settings
- A pause button that remains easy to access
- A temporary undo notification after risky actions

Feedback should be subtle enough not to distract the user but clear enough to build trust.

## 14. Safety and error prevention

Important safeguards include:

- Do not execute actions below a minimum confidence threshold
- Require stronger confirmation for closing, deleting, purchasing, or submitting
- Provide a short undo window where possible
- Pause input when the user leaves the camera frame
- Prevent repeated actions with gesture cooldowns
- Offer a “safe mode” that disables destructive gestures
- Always show camera and microphone status
- Process camera data locally wherever practical
- Avoid storing raw eye, face, hand, or voice recordings by default

## 15. Non-functional requirements

### Performance

- Gaze pointer updates should feel continuous
- Common gestures should be recognized within roughly 200–300 ms
- Speech transcription should appear incrementally
- End-to-end interaction latency should remain low enough to feel intentional

### Accuracy

- The gaze target should reliably land within a normal button-sized area after calibration
- Gesture false activations should be extremely rare
- The product should prefer ignoring an uncertain gesture over performing the wrong action

### Accessibility

- All visual feedback should have optional audio equivalents
- Gesture mappings and sensitivity should be customizable
- Users should not need to hold physically demanding poses
- Recognition should work across different skin tones and common assistive postures

### Privacy

- Request explicit camera and microphone permission
- Clearly communicate when either sensor is active
- Store calibration settings instead of raw recordings
- Provide a one-click way to delete saved user data

## 16. Recommended MVP

For the first working prototype, limit the scope to:

- One user and one monitor
- Webcam-based hand tracking
- Webcam-based approximate gaze tracking
- Gaze cursor with calibration
- Primary click
- Click-and-drag
- Vertical scrolling
- Zoom in/out
- Back navigation
- Pause/cancel gesture
- Voice dictation inside the currently focused text field
- Enter/submit gesture
- Basic visual feedback and confidence thresholds

Window closing and other destructive actions should wait until recognition is demonstrably reliable.

## 17. Success metrics

The MVP can be evaluated using:

- Percentage of intended targets selected correctly
- Gesture recognition accuracy
- Accidental action rate
- Average time required to click a target
- Average time required to complete a standard task
- Dictation word error rate
- Calibration time
- Number of recalibrations required per session
- User fatigue after 10–20 minutes
- Percentage of tasks completed without touching a mouse or keyboard

A useful demo benchmark would be completing this flow:

1. Open a browser.
2. Navigate to a website.
3. Select a search field.
4. Dictate a query.
5. Submit it with a gesture.
6. Open a result.
7. Scroll and zoom.
8. Navigate back.

## 18. Suggested technical structure

The system can be divided into five main components:

- **Vision layer:** Tracks eyes, face, and hand landmarks
- **Interpretation layer:** Smooths gaze and classifies gestures
- **Fusion layer:** Combines gaze position, gesture timing, and confidence
- **Action layer:** Converts recognized intent into operating-system actions
- **Interface layer:** Handles calibration, feedback, settings, and tutorials

Where available, the action layer should use operating-system accessibility APIs to identify actual buttons, text fields, and windows. This will be more reliable than treating every interaction as a raw screen coordinate.

## Key design recommendations

The most important recommendation is to avoid assigning too many gestures. Five highly reliable gestures will produce a better product than fifteen gestures users cannot remember or the camera cannot distinguish.

Other important considerations:

- Use gaze to indicate “where” and gestures to indicate “what.”
- Add target snapping for buttons, links, and text fields.
- Freeze or stabilize the gaze location when a gesture starts.
- Make pause/cancel the easiest gesture to perform.
- Avoid using ordinary resting movements as commands.
- Keep destructive gestures visually distinct from navigation gestures.
- Include a training mode that adapts thresholds to the individual user.
- Test fatigue early—large repeated arm motions can quickly become uncomfortable.
- Treat privacy indicators as a core feature because the camera and microphone may remain active for long periods.
- Start with web browsing as the primary demo environment; it offers a clear, recognizable end-to-end experience without requiring complete operating-system control.

## 19. Developer-tool extension

Chudvis should also provide a semantic IDE mode optimized for reviewing and directing coding
agents without a mouse or keyboard. The initial implementation targets VS Code and preserves the
general desktop controller as a separate mode.

The default bimanual model is:

- Gaze identifies the approximate editor target.
- The left or navigator hand moves between captured files and change ranges.
- The right or editor hand scrolls the active editor and confirms semantic selection.
- Voice supplies the natural-language edit request.
- A distinct confirmation gesture submits the request; an open palm cancels it.

IDE actions should operate on document symbols, ranges, files, and captured review entries rather
than raw screen coordinates whenever the editor exposes that information. Agent requests must show
their transcript and selected context before submission. Changes recorded after submission should
form an isolated review stack so unrelated existing work is not silently attributed to the agent.

The IDE bridge must remain local, versioned, bounded, reconnectable, and optional. Failure or absence
of the extension must not change the behavior of desktop mode.
