# ADR 0001: Represent pages as an indexed text view

**Status:** Accepted

## Context
The model has to see the page and point at elements. The options are raw HTML, screenshots with coordinates, or an accessibility-style text view.

## Decision
Snapshot visible interactive elements in the page, tag each with `data-wp-id`, and send the model one line per element (`[7] button "Add to cart"`) plus the visible text, truncated. Actions reference `element_id`.

## Consequences
- 10–50x fewer tokens than HTML, and it works with any text model.
- Clicks are exact, because there are no coordinates to miss.
- Ids change after every action, so the prompt insists on using only the latest state.
- Canvas-only or icon-only UIs are poorly described. Screenshot input is a future extension, and each step already captures one.
