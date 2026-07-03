GENERAL_REVIEW = "General termite service knowledge requiring business review"
CHECKLIST = "Flo-Zone Fume Checklist"
LIFT_RELEASE = "Flo-Zone Fumigation Property Lift Release"
VIKANE = "Vikane Fact Sheet"


KNOWLEDGE_BLOCKS = [
    {
        "title": "Drywood Termite Tenting Explained",
        "slug": "what-is-drywood-termite-tenting",
        "question": "What is drywood termite tenting?",
        "short_answer": (
            "Drywood termite tenting, also called structural fumigation, seals a structure so fumigant gas can "
            "reach termites hidden inside wood and concealed building spaces."
        ),
        "long_answer": (
            "Drywood termite tenting, also called structural fumigation, is a treatment in which the structure "
            "is covered and sealed. Fumigant gas then moves through the building to reach drywood termites hidden "
            "inside wood, wall voids, and other concealed areas that may not be accessible for direct treatment."
        ),
        "category": "drywood_termite_basics",
        "customer_type": "general",
        "confidence_level": "Medium",
        "source_notes": GENERAL_REVIEW,
    },
    {
        "title": "When Tenting Is Needed",
        "slug": "when-is-tenting-needed",
        "question": "When is tenting needed?",
        "short_answer": (
            "Tenting is commonly recommended when drywood termite activity is widespread, concealed, present in "
            "multiple areas, or difficult to reach with spot treatment."
        ),
        "long_answer": (
            "Whole-structure tenting is commonly recommended when drywood termite activity is widespread, hidden "
            "in multiple areas, or difficult to access. It may also be appropriate when the location or extent of "
            "active colonies means spot treatment may not reach all of the termite activity."
        ),
        "category": "tenting_process",
        "customer_type": "general",
        "confidence_level": "Medium",
        "source_notes": GENERAL_REVIEW,
    },
    {
        "title": "Fumigation Timing",
        "slug": "how-long-does-fumigation-take",
        "question": "How long does fumigation take?",
        "short_answer": (
            "Many fumigation jobs are completed over about 2-3 days, but timing depends on the structure, treatment "
            "plan, aeration, and clearance testing."
        ),
        "long_answer": (
            "Many structural fumigation jobs are commonly completed over about 2-3 days. The actual schedule varies "
            "with the structure, fumigation plan, time under seal, aeration conditions, and required clearance "
            "testing. Customers should follow the job-specific schedule from the fumigator rather than assume every "
            "structure will be ready in exactly 72 hours."
        ),
        "category": "tenting_process",
        "customer_type": "general",
        "confidence_level": "High",
        "source_notes": VIKANE,
    },
    {
        "title": "Items Homeowners Must Remove",
        "slug": "what-should-homeowners-remove",
        "question": "What should homeowners remove?",
        "short_answer": (
            "Occupants, pets, fish, plants, unsealed consumables, refrigerator and freezer food, waterproof bedding "
            "covers, and baby crib mattresses must be removed before fumigation."
        ),
        "long_answer": (
            "All occupants must vacate the structure. Pets, tropical fish, and plants must be removed. Food, "
            "beverages, medicines, tobacco, and other consumables must be removed unless they are properly sealed "
            "as directed. Food in refrigerators and freezers must also be removed. Waterproof mattress and pillow "
            "covers must be removed, and baby crib mattresses must be taken out of the structure."
        ),
        "category": "preparation",
        "customer_type": "homeowner",
        "confidence_level": "High",
        "source_notes": CHECKLIST,
    },
    {
        "title": "Fumigation Safety",
        "slug": "is-tenting-safe",
        "question": "Is tenting safe?",
        "short_answer": (
            "Fumigation must be performed by licensed professionals who follow label directions, legal requirements, "
            "aeration procedures, and clearance testing."
        ),
        "long_answer": (
            "Structural fumigation is safe only when licensed professionals perform the work according to product "
            "label directions, applicable law, aeration procedures, and clearance testing requirements. No occupant "
            "or unauthorized person should enter the structure until the fumigator has completed testing, cleared "
            "the structure for re-entry, and posted the required clearance notice."
        ),
        "category": "safety",
        "customer_type": "general",
        "confidence_level": "High",
        "source_notes": f"{CHECKLIST}; {VIKANE}",
    },
    {
        "title": "What Tenting Targets",
        "slug": "what-does-tenting-kill",
        "question": "What does tenting kill?",
        "short_answer": (
            "For Flo-Zone's primary service, structural fumigation targets active drywood termite infestations inside "
            "the structure at the time of treatment."
        ),
        "long_answer": (
            "Structural fumigation targets active infestations inside the structure at the time of treatment. "
            "Flo-Zone's public service wording focuses on active drywood termite infestations unless broader pest "
            "claims are separately reviewed and approved for use."
        ),
        "category": "vikane",
        "customer_type": "general",
        "confidence_level": "High",
        "source_notes": VIKANE,
    },
    {
        "title": "Limits of Tenting",
        "slug": "what-does-tenting-not-prevent",
        "question": "What does tenting not prevent?",
        "short_answer": (
            "Fumigation treats target pests present at the time of treatment; it does not create a permanent barrier "
            "against future drywood termite swarmers."
        ),
        "long_answer": (
            "Fumigation treats existing target pests inside the structure at the time of treatment, but it does not "
            "create a permanent barrier against future drywood termite swarmers or later reinfestation. It also does "
            "not replace a separate subterranean termite treatment when subterranean termites are present."
        ),
        "category": "limitations",
        "customer_type": "general",
        "confidence_level": "Medium",
        "source_notes": GENERAL_REVIEW,
    },
    {
        "title": "Termite Planning for Realtors",
        "slug": "how-should-realtors-handle-termite-issues",
        "question": "How should realtors handle termite issues?",
        "short_answer": (
            "Realtors should address drywood termite concerns early, encourage inspection, and communicate the "
            "preparation and timing requirements well before closing."
        ),
        "long_answer": (
            "Realtors should raise drywood termite concerns early in the transaction, encourage an appropriate "
            "inspection, and communicate preparation, access, treatment timing, and re-entry expectations clearly. "
            "Waiting until the last minute before closing can make scheduling and occupant coordination more difficult."
        ),
        "category": "realtors",
        "customer_type": "realtor",
        "confidence_level": "Medium",
        "source_notes": GENERAL_REVIEW,
    },
    {
        "title": "Commercial and Property Management Planning",
        "slug": "commercial-property-manager-fumigation-planning",
        "question": "What should commercial clients and property managers know?",
        "short_answer": (
            "Plan early for scheduling, occupant coordination, access, keys, preparation, possible lift needs, and "
            "operational downtime."
        ),
        "long_answer": (
            "Commercial clients and property managers should plan for treatment scheduling, tenant or occupant "
            "coordination, complete access, key handoff, preparation responsibilities, and expected downtime. The "
            "property layout and height may require a boom lift. A clear communication plan should identify who "
            "controls access, who confirms preparation, and when occupants or operations may return after clearance."
        ),
        "category": "commercial",
        "customer_type": "commercial",
        "confidence_level": "High",
        "source_notes": f"{CHECKLIST}; {LIFT_RELEASE}",
    },
    {
        "title": "Flo-Zone Fumigation Preparation Checklist",
        "slug": "flo-zone-fumigation-preparation-checklist",
        "question": "Flo-Zone fumigation preparation checklist",
        "short_answer": (
            "The checklist covers vacancy, pets and plants, consumables, utilities, access, landscaping, interior "
            "openings, exterior obstructions, and keys."
        ),
        "long_answer": (
            "All occupants must vacate, and pets, tropical fish, and plants must be removed. Food, beverages, "
            "medicines, tobacco, and consumables must be removed unless properly sealed; refrigerator and freezer "
            "food must be removed. Remove waterproof mattress and pillow covers and baby crib mattresses. Shut off "
            "automatic appliance controls, security alarms, and lighting systems where applicable. Natural or "
            "propane gas must be shut off and pilot lights extinguished, while electricity must remain available for "
            "fans. Cut back obstructing shrubs and branches, water the ground around nearby plants, and move rocks, "
            "gravel, wood chips, mulch, and loose material back from the foundation. Provide keys when fumigation "
            "starts. Open cabinets, drawers, closets, interior doors, attic covers, and trap doors. Awnings, cameras, "
            "antennas, guide wires, weather vanes, and other obstructions may need removal. The owner may need to "
            "remove and replace attached screened areas or fences. If the structure is not properly prepared, the "
            "fumigation may be rescheduled and a fee may apply."
        ),
        "category": "preparation",
        "customer_type": "general",
        "confidence_level": "High",
        "source_notes": CHECKLIST,
    },
    {
        "title": "Re-entry and Clearance",
        "slug": "reentry-and-clearance-explanation",
        "question": "Re-entry and clearance explanation",
        "short_answer": (
            "Customers must wait until the fumigator has aerated, tested, cleared, and posted the structure for "
            "re-entry."
        ),
        "long_answer": (
            "Customers must not enter until the fumigator has cleared the structure and posted the clearance notice, "
            "and they must not tamper with locking devices. The fumigator aerates the structure and measures remaining "
            "fumigant before reoccupancy. After re-entry, customers should obtain their keys, discard any food or "
            "medication accidentally left inside, and contact Flo-Zone immediately if anyone experiences discomfort."
        ),
        "category": "reentry_clearance",
        "customer_type": "general",
        "confidence_level": "High",
        "source_notes": f"{CHECKLIST}; {VIKANE}",
    },
    {
        "title": "Why Fumigation Is the Most Complete Treatment",
        "slug": "why-fumigation-is-most-complete-drywood-termite-treatment",
        "question": "Why is fumigation the most complete drywood termite treatment?",
        "short_answer": (
            "Whole-structure fumigation can reach hidden drywood termite activity in sealed structural spaces and "
            "inside wood that spot treatment may not access."
        ),
        "long_answer": (
            "Whole-structure fumigation is often the most complete treatment method for active drywood termite "
            "infestations because Vikane gas can move through sealed structural spaces, penetrate wood, and reach "
            "hidden termite activity that may not be accessible with spot treatment. Depending on the extent or "
            "location of the infestation, fumigation may be the only total-control method proven to eliminate certain "
            "structure-infesting pests."
        ),
        "category": "limitations",
        "customer_type": "general",
        "confidence_level": "High",
        "source_notes": VIKANE,
    },
    {
        "title": "About Vikane Fumigant Gas",
        "slug": "about-vikane-fumigant-gas",
        "question": "About Vikane fumigant gas",
        "short_answer": (
            "Vikane is a sulfuryl fluoride gas fumigant used in sealed structures so the gas can penetrate wood and "
            "reach hidden pests."
        ),
        "long_answer": (
            "Vikane is a sulfuryl fluoride gas fumigant. Because it is a gas, the structure is sealed so the fumigant "
            "can move through the building, penetrate wood and building contents, and reach hidden pests. Depending "
            "on the job, the building may remain sealed for 2-72 hours, followed by aeration and clearance testing "
            "before reoccupancy."
        ),
        "category": "vikane",
        "customer_type": "general",
        "confidence_level": "High",
        "source_notes": VIKANE,
    },
    {
        "title": "Vikane Warning Agent and Symptoms",
        "slug": "vikane-warning-agent-and-safety-symptoms",
        "question": "Vikane warning agent and safety symptoms",
        "short_answer": (
            "Sulfuryl fluoride is colorless and odorless, so a warning agent is added that can cause watery eyes and "
            "a scratchy throat."
        ),
        "long_answer": (
            "Sulfuryl fluoride is colorless and odorless, so a warning agent is added that can cause watery eyes and "
            "a scratchy throat. If anyone experiences those symptoms in a recently fumigated structure, they should "
            "leave immediately and call the pest control company so the structure can be retested."
        ),
        "category": "safety",
        "customer_type": "general",
        "confidence_level": "High",
        "source_notes": VIKANE,
    },
    {
        "title": "Drywood Termite Droppings",
        "slug": "what-are-drywood-termite-droppings",
        "question": "What are drywood termite droppings?",
        "short_answer": (
            "Drywood termite droppings are small, dry fecal pellets called frass that termites push from tiny "
            "kick-out holes."
        ),
        "long_answer": (
            "Drywood termite droppings are called fecal pellets or frass. Termites push these small, dry pellets out "
            "of tiny kick-out holes in infested wood. Homeowners often mistake the piles for sawdust, sand, pepper, "
            "or dirt."
        ),
        "category": "identification",
        "customer_type": "homeowner",
        "confidence_level": "Medium",
        "source_notes": GENERAL_REVIEW,
    },
    {
        "title": "Drywood Termite Wings",
        "slug": "what-do-drywood-termite-wings-look-like",
        "question": "What do drywood termite wings look like?",
        "short_answer": (
            "Drywood termite swarmers shed small, same-sized wings that may collect near windows, doors, lights, or "
            "entry points."
        ),
        "long_answer": (
            "Drywood termite swarmers shed their wings after swarming. Customers may find small wings of roughly the "
            "same size near windowsills, doors, lights, or other entry points. Finding shed wings is a strong reason "
            "to schedule a professional inspection."
        ),
        "category": "identification",
        "customer_type": "homeowner",
        "confidence_level": "Medium",
        "source_notes": GENERAL_REVIEW,
    },
    {
        "title": "Signs of Drywood Termites",
        "slug": "how-to-know-if-you-have-drywood-termites",
        "question": "How do I know if I have drywood termites?",
        "short_answer": (
            "Common signs include dry pellets or frass, kick-out holes, shed wings, swarmers, and blistered or "
            "damaged wood."
        ),
        "long_answer": (
            "Possible drywood termite signs include dry fecal pellets or frass, tiny kick-out holes, shed wings, "
            "visible swarmers, and blistered or damaged wood. Activity may appear around windows, attics, trim, "
            "furniture, or other exposed wood. A professional inspection is the appropriate next step when these "
            "signs are present."
        ),
        "category": "identification",
        "customer_type": "homeowner",
        "confidence_level": "Medium",
        "source_notes": GENERAL_REVIEW,
    },
    {
        "title": "Boom Lift Requirements and Property Access",
        "slug": "why-boom-lift-is-needed-for-tall-structures",
        "question": "Why is a boom lift needed on structures taller than one story?",
        "short_answer": (
            "A boom lift may be needed to place and seal fumigation tarps safely on tall buildings, steep rooflines, "
            "and upper sections that ladders cannot practically reach."
        ),
        "long_answer": (
            "A boom lift may be needed for structures taller than one story because fumigation tarps must be safely "
            "and properly placed over the structure. Multi-story buildings, steep rooflines, tall walls, chimneys, "
            "dormers, and roof obstacles can make ladder-only access unsafe or impractical. A lift helps the crew "
            "position tarps, reach upper sections, improve the seal, and reduce unsafe climbing. Lift access can "
            "affect the property: lifts may leave yard ruts and may pose risks to sidewalks, driveways, sprinkler "
            "lines, septic tanks, grease traps, fences, shrubs, and other surrounding areas. Customers should mark "
            "areas that cannot be driven over and discuss them with Flo-Zone before fumigation."
        ),
        "category": "preparation",
        "customer_type": "property_manager",
        "confidence_level": "High",
        "source_notes": LIFT_RELEASE,
    },
]


for sort_order, block in enumerate(KNOWLEDGE_BLOCKS, start=1):
    block["sort_order"] = sort_order
    block["status"] = "active"
