# MyTransportTimes Livery Team Training Guide
- [How to make livery](#how-to-make-a-css-livery)
   - [1 Straight lines]()
       - [1.1 Stacking Gradients](#11-straight-lines-2-colours)
       - [1.2 More Colours](#12-more-colours)
       - [1.3 Stacking Gradients](#13-stacking-gradients)
       - [1.4 Gradient directions](#14-gradient-directions)
   - [2. Radial Gradients](#2-radial-gradients)
        - [2.1 Radial gradients](#21-radial-gradients)
        - [2.2 Radial gradient position](#22-radial-gradient-position)
        - [2.3 Radial gradient examples](#23-radial-gradient-examples)
   - [3. Conic Gradients](#3-conic-gradients)
        - [3.1 What is a conic gradient?](#31-what-is-a-conic-gradient)
        - [3.2 Conic gradient position and start angle](#32-conic-gradient-position-and-start-angle)
        - [3.3 Stacking conic gradients](#33-stacking-conic-gradients)
        - [3.4 Repeating conic gradients](#34-repeating-conic-gradients)
        - [3.5 Conic gradient examples](#35-conic-gradient-examples)
   - [4. Flipping Liverys](#4-flipping-liverys)
        - [4.1 Flipping linear gradients](#41-flipping-linear-gradients)
        - [4.2 Flipping radial gradients](#42-flipping-radial-gradients)
        - [4.3 Flipping conic gradients](#43-flipping-conic-gradients)

## How to make a CSS livery
### 1. Basic CSS gradients
#### 1.1 Straight lines (2 colours)
The most basic form of CSS gradients is the linear gradient.

Example:
```CSS
linear-gradient(#ffffff 50%, transparent 50%)
```
Breakdown:
```CSS
linear-gradient  /*This is the type of gradient*/
(
    #ffffff 50%, /*Defining the colour #ffffff from 0% to 50%*/
    transparent 50%  /*Defining the colour transparent from 50% to 100%*/
)
```
We don't need to add 0% or 100% to these because it is just the 2 colours.

#### 1.2 More Colours
If we add a 3rd colour we would need to define where that colour starts and where it ends.

Breakdown:
```CSS
linear-gradient      /*This is the type of gradient*/
(
    #ffffff 45%,     /*Defining the colour #ffffff from 0% to 45%*/
    #ff0000 45% 55%, /*Defining the colour #ff0000 from 45% to 55%*/
    transparent 55%  /*Defining the colour transparent from 55% to 100%*/
)
```
Here we have to tell it that we want the colour #ff0000 to start at 45% and go until 55%.

#### 1.3 Stacking Gradients
We can also stack gradients to create different shapes.

Example:
```CSS
linear-gradient(to bottom, transparent 45%, #ff0000 45% 65%, transparent 65%),
linear-gradient(to left, #ffffff 45%, #ff0000 45% 55%, #ffffff 55%)
```
Here we are stacking two gradients.

Breakdown:
```CSS
linear-gradient
(
    to bottom,         /*Define the direction of the gradient*/
    transparent 45%,   /*Define the first 45% to be transparent, you can also use #0000*/
    #ff0000 45% 65%,   /*Define 45% to 65% to be #ff0000 (red)*/
    transparent 65%    /*Define the final 65% to 100% as transparent*/
),                     /*Adding a , here allows us to add another gradient*/
linear-gradient
(
    to left,           /*Define the direction of the gradient*/
    #ffffff 45%,       /*Define the colour #ffffff from 0% to 45%*/
    #ff0000 45% 55%,   /*Define the colour #ff0000 from 45% to 55%*/
    #ffffff 55%        /*Define the colour #ffffff from 55% to 100%*/
)
```
Here we use a `,` to start two CSS gradients on top of each other.  
We use `transparent` / `#0000` to allow the other gradient underneath to show.

#### 1.4 Gradient directions
With CSS gradients we have 2 main options for defining their directions:
1. We can use terms such as `to top`, `to bottom`, `to top left`
2. We can also define a specific angle by using `20deg` — this allows us to set it to any angle we want

---

### 2. Radial Gradients
#### 2.1 Radial gradients
Radial gradients allow us to make ellipses and circles and can be stacked in the same way as a linear gradient.  
You can also stack any type of gradient on top of any other type.

Examples:
```CSS
radial-gradient(circle, red 30%, yellow 30% 40%, green 40%)
```
```CSS
radial-gradient(circle, red 30%, yellow 30% 40%, #0000 40%),
linear-gradient(to left, #ffffff 45%, #ff0000 45% 55%, #ffffff 55%)
```
Breakdown:
```CSS
radial-gradient(
    circle,         /*Define the shape of the gradient*/
    at 10% 10%,     /*Define the position of the gradient*/
    red 30%,        /*Define the colour red from 0% to 30%*/
    yellow 30% 40%, /*Define the colour yellow from 30% to 40%*/
    green 40%       /*Define the colour green from 40% to 100%*/
)
```

#### 2.2 Radial gradient position
The `at X% Y%` part of a radial gradient defines where the centre of the circle is placed.

- `at 50% 50%` — centre of the element (default)
- `at 0% 50%` — left edge, halfway down
- `at -20% 25%` — outside the left edge, a quarter of the way down

You can push the centre **outside** the element using values below 0% or above 100%. This is very useful for creating partial circles that appear to come from an edge or corner of the livery — only part of the circle will be visible.

#### 2.3 Radial gradient examples

**Example 1 — Circle from the left edge:**
```CSS
radial-gradient(circle at -20% 25%, #25b0cf 48%, #64cde5 48% 56%, #fff 56% 62%, #25b0cf 62%)
```
Breakdown:
```CSS
radial-gradient(
    circle at -20% 25%,  /*Circle centred just off the left edge, 25% down*/
    #25b0cf 48%,         /*Inner colour from 0% to 48%*/
    #64cde5 48% 56%,     /*Lighter ring from 48% to 56%*/
    #fff    56% 62%,     /*White ring from 56% to 62%*/
    #25b0cf 62%          /*Outer colour from 62% to 100%*/
)
```
Because the circle centre is at -20%, only the right side of the circle is visible — creating a curved stripe effect coming from the left edge.

**Example 2 — Circle from the top-left corner:**
```CSS
radial-gradient(circle at -30% -30%, #2d6ec6 50%, #fb0 50% 80%, #333 80%)
```
Breakdown:
```CSS
radial-gradient(
    circle at -30% -30%, /*Circle centred off the top-left corner*/
    #2d6ec6 50%,         /*Blue inner area*/
    #fb0    50% 80%,     /*Yellow ring*/
    #333    80%          /*Dark outer area*/
)
```

---

### 3. Conic Gradients
#### 3.1 What is a conic gradient?
A conic gradient sweeps colours around a centre point — think of it like the hands of a clock sweeping around. The easiest way to think about it is: **conic gradients make triangles and pie slices**.

When you set a colour to fill a range of degrees (e.g. `0deg` to `110deg`), it fills a triangle/wedge shape from the centre point.

Basic example:
```CSS
conic-gradient(red 0deg 90deg, blue 90deg 180deg, green 180deg 360deg)
```
This creates three equal pie slices — red on the top-right, blue on the bottom-right, green on the left.

Breakdown:
```CSS
conic-gradient(
    red   0deg 90deg,   /*Red wedge from 0 to 90 degrees*/
    blue  90deg 180deg, /*Blue wedge from 90 to 180 degrees*/
    green 180deg 360deg /*Green wedge from 180 to 360 degrees*/
)
```
Using `#0000` (transparent) for some wedges lets you hide parts of the triangle, leaving only the visible slice showing over the layers below.

#### 3.2 Conic gradient position and start angle
Conic gradients have two extra controls: **where the centre is** and **what angle it starts from**.

```CSS
conic-gradient(from 270deg at 33% 50%, ...)
```

- `from 270deg` — the sweep starts at 270 degrees (pointing left/west) instead of the default 0deg (pointing up/north)
- `at 33% 50%` — the centre point is at 33% across and 50% down the element

You can move the centre **outside** the element (below 0% or above 100%) just like with radial gradients. This means the visible part of the "pie" becomes just a corner or strip of the full circle, which is great for creating diagonal cuts and sharp-edged shapes.

Breakdown of a real livery conic layer:
```CSS
conic-gradient(from 270deg at 33%, #464fb8 110deg, #0000 110deg 360deg)
```
```CSS
conic-gradient(
    from 270deg       /*Start the sweep pointing left*/
    at 33%,           /*Centre point at 33% across, 50% down (default Y)*/
    #464fb8 110deg,   /*Fill blue from the start (270deg) for 110 degrees*/
    #0000 110deg 360deg /*Everything else is transparent*/
)
```
The blue fills a 110-degree wedge starting from the left side of the element — this creates a solid triangular shape pointing into the livery.

#### 3.3 Stacking conic gradients
Just like linear and radial gradients, conic gradients can be stacked using a `,`. You can mix conic, radial, and linear gradients all together in a single livery.

A complex livery might look like:
```CSS
conic-gradient(from 270deg at 33%,   #464fb8 110deg, #0000 110deg 360deg),
conic-gradient(from 270deg at 64% 20%, #464fb8 110deg, #0000 110deg 360deg),
conic-gradient(from 270deg at 40% 40%, #758cfe 110deg, #0000 110deg 360deg),
linear-gradient(#3f4073 0% 15%, #758cfe 10% 20%, #464fb8 20% 68%, #758cfe 68% 78%)
```
Here, multiple conic triangles are layered at different positions and sizes to build up a complex shape, with a linear gradient providing the base background behind them all.

**Key tips for stacking:**
- Put the most detailed / topmost shapes first
- Put the base background colour or solid layer last
- Use `#0000` to let layers beneath show through

#### 3.4 Repeating conic gradients
Just like `repeating-linear-gradient`, there is also `repeating-conic-gradient`. This repeats the pattern around the full 360 degrees.

Example:
```CSS
repeating-conic-gradient(from 227deg at 78% 97%, #0000 0deg 90deg, #ffffff 90deg 95deg, #fff0 95deg 97deg, #ffffff 97deg 102deg, #0000 102deg 360deg)
```
Breakdown:
```CSS
repeating-conic-gradient(
    from 227deg at 78% 97%, /*Start at 227deg, centre near bottom-right corner*/
    #0000    0deg 90deg,    /*Transparent gap*/
    #ffffff  90deg 95deg,   /*Thin white stripe*/
    #fff0    95deg 97deg,   /*Transparent gap*/
    #ffffff  97deg 102deg,  /*Another thin white stripe*/
    #0000    102deg 360deg  /*Transparent for the rest*/
)
```
The `repeating-` prefix makes this pattern tile around the full 360 degrees — great for thin accent lines that radiate from a corner.

#### 3.5 Conic gradient examples

**Example 1 — Multi-layer conic livery:**
```CSS
conic-gradient(from 270deg at 33%,#464fb8 110deg,#0000 110deg 360deg),
conic-gradient(from 270deg at 64% 20%,#464fb8 110deg,#0000 110deg 360deg),
conic-gradient(from 270deg at 40% 40%,#758cfe 110deg,#0000 110deg 360deg),
conic-gradient(from 270deg at 37.5%,#464fb8 110deg,#0000 110deg 360deg),
conic-gradient(from 90deg at 84%,#3f4073 110deg,#0000 110deg 360deg),
linear-gradient(#0000 20%,#ab985a 20% 50%,#0000 50%),
linear-gradient(#0000 80%,#ab985a 80% 83%,#3f4073 83%),
linear-gradient(110deg,#0000 55%,#758cfe 55% 60%,#ab985a 60% 78%,#0000 78%),
linear-gradient(#3f4073 0% 15%,#758cfe 10% 20%,#464fb8 20% 68%,#758cfe 68% 78%)
```
This livery builds up depth by stacking five conic triangle layers at different positions, then adds three linear gradient stripes for detail, with a solid linear background at the base.

**Example 2 — Conic with radial overlay:**
```CSS
conic-gradient(from 40deg at 68%,#0000 100deg,#fbff008c 100deg 180deg,#ff8800a4 180deg 280deg,#ff5100a6 280deg),
radial-gradient(circle at 68%,#d9ff0077 35%,#0000 35%),
conic-gradient(from 40deg at 68%,#79bf48 100deg,red 100deg 180deg,#0000 180deg),
radial-gradient(circle at 68%,#f70067 35%,#0000 35%),
conic-gradient(from 40deg at 68%,#0000 180deg,#e5ff00 180deg)
```
This example mixes conic and radial gradients all centred at the same point (`68%`). The radial gradients create solid circular spots on top, while the conic layers add the coloured wedge shapes behind and around them. Note the use of semi-transparent colours (e.g. `#fbff008c`) — the `8c` at the end is the alpha/opacity value in hex, allowing layers below to blend through.

---

### 4. Flipping Liverys
Flipping liverys can get a bit complex depending on the type of gradient.

#### 4.1 Flipping linear gradients
Linear gradients are the easiest to flip — you simply negate the angle.

Pre-flip:
```CSS
linear-gradient(300deg,  #333 28%, #0000 28%),
linear-gradient(#0000 85%, #fb0 85%),
linear-gradient(300deg,  #0000 31%, #333 31% 39%, #0000 39%),
linear-gradient(#0000 40%, #fb0 40%),
linear-gradient(300deg,  #0000 80%, #333 20%),
#fb0
```
Post-flip:
```CSS
linear-gradient(-300deg, #333 28%, #0000 28%),
linear-gradient(#0000 85%, #fb0 85%),
linear-gradient(-300deg, #0000 31%, #333 31% 39%, #0000 39%),
linear-gradient(#0000 40%, #fb0 40%),
linear-gradient(-300deg, #0000 80%, #333 20%),
#fb0
```
Gradients with no angle (vertical ones like `linear-gradient(#0000 85%, #fb0 85%)`) don't need to change — they are already symmetrical.

#### 4.2 Flipping radial gradients
Radial gradients need their horizontal position reflected. To flip the X position, use this formula:

> **New X% = 100% − Old X%**  
> (If the value goes below 0%, subtract from 100% the same way — e.g. -30% becomes 130%)

Pre-flip:
```CSS
radial-gradient(circle at -30% -30%, #2d6ec6 50%, #fb0 50% 80%, #333 80%)
```
Post-flip:
```CSS
radial-gradient(circle at 130% -30%, #2d6ec6 50%, #fb0 50% 80%, #333 80%)
```
The X position went from `-30%` to `130%` (100 - (-30) = 130). The Y position stays the same.

#### 4.3 Flipping conic gradients
Conic gradients are the most complex to flip. You need to change three things:

1. **The `from` angle** — reflect it: `New angle = 360° − Old angle` (or equivalently, negate and add 360)  
   However, if you also need to shift the sweep direction, you may need to adjust by adding or subtracting 180°. Look at what the triangle is pointing at and work out where it needs to point after flipping.

2. **The `at X%` position** — reflect the X the same way as radial: `New X% = 100% − Old X%`

3. **The colour stop order** — because the sweep is now mirrored, the wedge colours may need to be reordered so they appear in the correct visual position.

Pre-flip (simple example):
```CSS
repeating-conic-gradient(from 227deg at 78% 97%, #0000 0deg 90deg, #ffffff 90deg 95deg, #fff0 95deg 97deg, #ffffff 97deg 102deg, #0000 102deg 360deg),
linear-gradient(235deg, #0000d9 45%, #00a2ff 45%)
```
Post-flip:
```CSS
repeating-conic-gradient(from 301deg at 22% 97%, #0000 0deg 90deg, #ffffff 90deg 95deg, #fff0 95deg 97deg, #ffffff 97deg 102deg, #0000 102deg 360deg),
linear-gradient(125deg, #0000d9 45%, #00a2ff 45%)
```
- `from 227deg` → `from 301deg` (360 − 227 = 133... adjusted to 301 to keep the stripe pointing correctly after the X-flip)
- `at 78%` → `at 22%` (100 − 78 = 22)
- `235deg` linear → `125deg` linear (negated/reflected angle)

Pre-flip (complex example):
```CSS
conic-gradient(from 40deg at 68%,#0000 100deg,#fbff008c 100deg 180deg,#ff8800a4 180deg 280deg,#ff5100a6 280deg),
radial-gradient(circle at 68%,#d9ff0077 35%,#0000 35%),
conic-gradient(from 40deg at 68%,#79bf48 100deg,red 100deg 180deg,#0000 180deg),
radial-gradient(circle at 68%,#f70067 35%,#0000 35%),
conic-gradient(from 40deg at 68%,#0000 180deg,#e5ff00 180deg)
```
Post-flip:
```CSS
conic-gradient(from -40deg at 32%,#ff5100a6 80deg,#ff8800a4 80deg 180deg,#fbff008c 180deg 260deg,#0000 260deg),
radial-gradient(circle at 32%,#d9ff0077 35%,#0000 35%),
conic-gradient(from 140deg at 32%,red 80deg,#79bf48 80deg 180deg,#0000 180deg),
radial-gradient(circle at 32%,#f70067 35%,#0000 35%),
conic-gradient(from 140deg at 32%,#0000 180deg,#e5ff00 180deg)
```
Changes made:
- `at 68%` → `at 32%` on all layers (100 − 68 = 32)
- `from 40deg` → `from -40deg` on the outer cone (negated to mirror the sweep direction)
- `from 40deg` → `from 140deg` on the inner cones (40 + 100 = 140, shifted to account for the reordered stops)
- Colour stop order reversed so the wedge colours appear visually correct after the flip
- Radial X positions also updated to match (68% → 32%)

**General tip for conic flips:** work through each layer one at a time, adjust the `at X%`, adjust the `from` angle, then check whether the stop order needs reversing.
