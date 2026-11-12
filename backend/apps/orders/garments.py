"""Built-in pick lists for garment details at order entry.

Garments store the chosen words, not references, so these lists can later become
editable per store without changing saved orders.
"""

# (name, swatch hex or '' when a swatch doesn't make sense)
COLORS = [
    ('Black', '#000000'), ('White', '#FFFFFF'), ('Gray', '#808080'), ('Navy', '#000080'),
    ('Blue', '#0000FF'), ('Blue (Light)', '#ADD8E6'), ('Blue (Royal)', '#4169E1'), ('Brown', '#A52A2A'),
    ('Beige', '#F5F5DC'), ('Cream', '#FFFDD0'), ('Burgundy', '#800020'), ('Red', '#FF0000'),
    ('Pink', '#FFC0CB'), ('Purple', '#800080'), ('Green', '#008000'), ('Olive', '#808000'),
    ('Yellow', '#FFFF00'), ('Orange', '#FFA500'), ('Gold', '#D4AF37'), ('Silver', '#C0C0C0'),
    ('Khaki', '#C3B091'), ('Tan', '#D2B48C'), ('Charcoal', '#36454F'), ('Teal', '#008080'),
    ('Turquoise', '#40E0D0'), ('Lavender', '#E6E6FA'), ('Maroon', '#800000'), ('Ivory', '#FFFFF0'),
    ('Camel', '#C19A6B'), ('Coral', '#FF7F50'), ('Mint', '#98FF98'), ('Peach', '#FFE5B4'),
    ('Off white', '#FAF9F6'), ('Gray (light)', '#D3D3D3'), ('Green (light)', '#90EE90'), ('Plum', '#8E4585'),
    ('Dark', ''), ('Light', ''), ('Multicolor', ''), ('Check', ''), ('Stripe', ''), ('Dot', ''),
    ('Floral', ''), ('Print', ''),
]

DAMAGES = [
    'Hole', 'Tear', 'Missing button', 'Broken button', 'Broken zipper', 'Loose seam', 'Iron shine',
    'Iron mark', 'Faded', 'Color loss', 'Dye transfer', 'Pilling', 'Snag', 'Burn', 'Bubbling', 'Shrinkage',
    'Collar torn', 'Cuff torn', 'Worn collar', 'Worn cuffs', 'Missing belt', 'Frayed',
]

STAINS = [
    'Unknown', 'Oil / grease', 'Food', 'Wine', 'Coffee / tea', 'Alcohol', 'Ink', 'Blood', 'Makeup',
    'Perfume', 'Sweat', 'Deodorant', 'Grass', 'Mud', 'Rust', 'Paint', 'Wax', 'Bleach', 'Mildew',
    'Color bleed', 'Soiled collar', 'Water mark', 'Yellowing', 'Set stain',
]

MATERIALS = [
    'Cotton', 'Linen', 'Wool', 'Cashmere', 'Silk', 'Polyester', 'Nylon', 'Rayon / viscose', 'Acetate',
    'Spandex', 'Denim', 'Leather', 'Suede', 'Shearling', 'Fur', 'Velvet', 'Satin', 'Chiffon', 'Lace',
    'Down', 'Corduroy',
]

PATTERNS = ['Solid', 'Striped', 'Pinstripe', 'Check / plaid', 'Argyle', 'Houndstooth', 'Herringbone',
            'Polka dot', 'Floral', 'Paisley', 'Print', 'Tie-dye', 'Camouflage', 'Animal print', 'Metallic',
            'Ribbed', 'Distressed', 'Reversible']

STYLES = ['Long sleeve', 'Short sleeve', 'Sleeveless', 'Double-breasted', 'Single-breasted', 'Pleated',
          'Flat front', 'Cuffed', 'Hooded', 'Pullover', 'Skinny', 'Capri', "Children's", 'Lined', 'Beaded',
          'Sequined', 'Embroidered', 'Wrinkle-free']

# A garment records at most this many of each.
MAX_CHOICES = {'colors': 2, 'damages': 3, 'stains': 3, 'materials': 3, 'patterns': 3, 'styles': 3}

# Field name on OrderItem → allowed values.
LIST_FIELDS = {
    'colors': [name for name, _ in COLORS],
    'damages': DAMAGES,
    'stains': STAINS,
    'materials': MATERIALS,
    'patterns': PATTERNS,
    'styles': STYLES,
}
