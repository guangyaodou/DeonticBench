EXAMPLE_AIRLINE_1_ONLY = """
% Text
% Sarah is a Main Cabin Class passenger flying from Orlando to Philadelphia with the following items: 1. A backpack: 22 x 13 x 6 inches, 10 lbs; 2. A luggage box: 44 x 22 x 20 inches, 69 lbs; 3. A luggage box: 34 x 18 x 12 inches, 51 lbs; 4. A backpack: 38 x 22 x 16 inches, 84 lbs; 5. A backpack: 38 x 14 x 11 inches, 90 lbs; Sarah's flight ticket is $180.

% Question
% What is the total cost (including the flight ticket fee, checked bag fees, cost of special needs) according to the policies for the passenger?

% Facts
```prolog
/* ----------  Rules from the statutes that are relevant  ---------- */

/* carry-on limits */
carry_on_max(22,14,9).

/* domestic checked-bag fees for Main Cabin */
checked_fee(1, 40).   /* 1st checked bag          */
checked_fee(2, 45).   /* 2nd checked bag          */
checked_fee(3,150).   /* 3rd checked bag          */
checked_fee(N,200) :- N>=4.   /* 4th bag and beyond */

/* oversize fees – within U.S. / Canada / PR / USVI */
oversize_fee(Dim,30) :- Dim>62, Dim=<65.
oversize_fee(Dim,200) :- Dim>65, Dim=<115.
oversize_fee(Dim,0) :- Dim=<62.             /* not oversize */

/* overweight fees – within U.S. / Canada / PR / USVI */
overweight_fee(W,30)  :- W>50 , W=<53.
overweight_fee(W,100) :- W>53 , W=<70.
overweight_fee(W,200) :- W>70 , W=<100.
overweight_fee(W,0)   :- W=<50.

/* extra fee for a bag that is both oversize and/or overweight      */
/* “the higher fee … applies, in addition to the checked-bag fee.”  */
extra_fee(Dim,W,Fee) :-
    oversize_fee(Dim,OS),
    overweight_fee(W,OW),
    (OS>=OW -> Fee=OS ; Fee=OW).

/* ----------  Facts describing Sarah’s flight and bags  ---------- */

flight_ticket(180).
cabin(main_cabin).
route(domestic).           /* Orlando-Philadelphia inside U.S. */

/* bag(Id,Length,Width,Height,Weight) */
bag(1,22,13, 6, 10).    /* backpack – will be carry-on        */
bag(2,44,22,20, 69).
bag(3,34,18,12, 51).
bag(4,38,22,16, 84).
bag(5,38,14,11, 90).

/* ----------  Helper predicates  ---------- */

/* sum of the three dimensions */
dim_sum(Id,Sum) :- bag(Id,L,W,H,_), Sum is L+W+H.

/* does the bag fit the carry-on limits?  */
carry_on(Id) :-
    bag(Id,L,W,H,_),
    carry_on_max(MaxL,MaxW,MaxH),
    L=<MaxL, W=<MaxW, H=<MaxH.

/* checked bag ordering (exclude the single carry-on) */
checked_bag_number(Id,N) :-
    findall(B,(bag(B,_,_,_,_), \\+ carry_on(B)), Bs),
    nth1(N,Bs,Id).

/* fee for one checked bag (includes base checked fee plus extra) */
bag_total_fee(Id,Total) :-
    checked_bag_number(Id,N),
    checked_fee(N,Base),
    dim_sum(Id,Dim),
    bag(Id,_,_,_,W),
    extra_fee(Dim,W,Extra),
    Total is Base + Extra.

/* sum of all checked-bag fees */
total_checked_bag_fees(Sum) :-
    findall(F, (bag_total_fee(_,F)), Fs),
    sum_list(Fs,Sum).

/* ----------  Grand total (ticket + all luggage charges) ---------- */
total_cost(Total) :-
    flight_ticket(Tix),
    total_checked_bag_fees(Bags),
    Total is Tix + Bags.

/* ----------  Query and output ---------- */
:- total_cost(Total), format('Total cost: ~w~n',[Total]).
:- halt.

"""
EXAMPLE_AIRLINE_2_ONLY = """% Text
% Thomas is a First Class passenger flying from Montreal to Portland with the following items: 1. A backpack: 19 x 11 x 7 inches, 6 lbs; 2. A luggage box: 36 x 22 x 14 inches, 55 lbs; 3. A luggage box: 37 x 18 x 9 inches, 80 lbs; 4. A backpack: 34 x 20 x 10 inches, 61 lbs; 5. A backpack: 36 x 20 x 9 inches, 95 lbs; 6. A backpack: 44 x 28 x 21 inches, 78 lbs; 7. A backpack: 33 x 20 x 10 inches, 83 lbs; 8. A luggage box: 38 x 16 x 9 inches, 68 lbs; 9. A luggage box: 34 x 21 x 9 inches, 99 lbs; 10. A backpack: 33 x 21 x 10 inches, 81 lbs; 11. A backpack: 44 x 31 x 21 inches, 72 lbs; Thomas's flight ticket is $235.

% Question
% What is the total cost (including the flight ticket fee, checked bag fees, cost of special needs) according to the policies for the passenger?

/* ----------  Facts describing the trip -------------------- */


/* ticket price */
flight_cost(235).


/* list of checked bags: bag(Id,Length,Width,Height,Weight). */
bag(2,36,22,14,55).
bag(3,37,18, 9,80).
bag(4,34,20,10,61).
bag(5,36,20, 9,95).
bag(6,44,28,21,78).
bag(7,33,20,10,83).
bag(8,38,16, 9,68).
bag(9,34,21, 9,99).
bag(10,33,21,10,81).
bag(11,44,31,21,72).


/* list (constant) of all checked-bag Ids */
checked_bag_ids([2,3,4,5,6,7,8,9,10,11]).


/* ----------  Statutory rules (for this itinerary) --------- */


/* sum of dimensions */
dims_sum(L,W,H,S) :- S is L+W+H.


/* oversize fee for: Within / between U.S. and Canada */
oversize_fee(Sum,Fee) :-
       (   Sum =< 62      -> Fee = 0
       ;   Sum =< 65      -> Fee = 30
       ;   Sum =< 115     -> Fee = 200 ).


/* overweight fee for: Within / between U.S. and Canada          */
/* Threshold is 50 lbs for CHARGED bags, 70 lbs for COMPLIMENTARY */
overweight_fee(W,Thresh,Fee) :-
       (   W =< Thresh        -> Fee = 0
       ;   W =< 53            -> Fee = 30
       ;   W =< 70            -> Fee = 100
       ;   W =< 100           -> Fee = 200 ).


/* penalty for a bag: higher of over-size vs over-weight */
penalty(BagId,comp,Pen) :-
       bag(BagId,L,W,H,Weight),
       dims_sum(L,W,H,Sum),
       oversize_fee(Sum,OS),
       overweight_fee(Weight,70,OW),         % complimentary ⇒ 70-lb limit
       Pen is max(OS,OW).


penalty(BagId,charged,Pen) :-
       bag(BagId,L,W,H,Weight),
       dims_sum(L,W,H,Sum),
       oversize_fee(Sum,OS),
       overweight_fee(Weight,50,OW),         % charged bag ⇒ 50-lb limit
       Pen is max(OS,OW).


/* checked-bag fee by ordinal position for First Class on this route */
bag_fee(1,0).
bag_fee(2,0).
bag_fee(3,150).
bag_fee(N,200) :- N>=4.


/* ----------  Helper predicates ---------------------------- */


/* choose 2 different elements (F1<F2) from a list */
choose_two(List,F1,F2) :-
       append(_,[F1|Tail],List),
       member(F2,Tail).


/* remove chosen freebies from the master list to build the ordered list */
ordered_list(F1,F2,Ordered) :-
       checked_bag_ids(All),
       select(F1,All,Rest1),
       select(F2,Rest1,Rest),
       Ordered = [F1,F2|Rest].          % freebies go in positions 1 and 2


/* compute cost for a particular choice of freebies */
cost_for_choice(F1,F2,Total) :-
       ordered_list(F1,F2,Ordered),
       cost_bags(Ordered,1,CostBags,Penalties),
       flight_cost(Flight),
       Total is Flight + CostBags + Penalties.


/* walk through ordered list accumulating bag fees and penalties */
cost_bags([],_,0,0).
cost_bags([Bag|Bs],Idx,CostSum,PenSum) :-
       (Idx =< 2 -> Type = comp ; Type = charged),
       bag_fee(Idx,Fee),
       penalty(Bag,Type,Pen),
       NextIdx is Idx+1,
       cost_bags(Bs,NextIdx,CostRest,PenRest),
       CostSum is Fee + CostRest,
       PenSum  is Pen + PenRest.


/* compute minimal total cost over all ways of selecting 2 complimentary bags */
total_cost(MinTotal) :-
       checked_bag_ids(L),
       findall(T,
               ( choose_two(L,F1,F2),
                 cost_for_choice(F1,F2,T)),
               Totals),
       min_list(Totals,MinTotal).


/* ----------  Run the query and print ----------------------- */
:- total_cost(Total), format('Total cost: ~w~n',[Total]).
:- halt.
```
"""

EXAMPLE_AIRLINE = """Example 1:

% Text
% Sarah is a Main Cabin Class passenger flying from Orlando to Philadelphia with the following items: 1. A backpack: 22 x 13 x 6 inches, 10 lbs; 2. A luggage box: 44 x 22 x 20 inches, 69 lbs; 3. A luggage box: 34 x 18 x 12 inches, 51 lbs; 4. A backpack: 38 x 22 x 16 inches, 84 lbs; 5. A backpack: 38 x 14 x 11 inches, 90 lbs; Sarah's flight ticket is $180.

% Question
% What is the total cost (including the flight ticket fee, checked bag fees, cost of special needs) according to the policies for the passenger?

% Facts
```prolog
/* ----------  Rules from the statutes that are relevant  ---------- */

/* carry-on limits */
carry_on_max(22,14,9).

/* domestic checked-bag fees for Main Cabin */
checked_fee(1, 40).   /* 1st checked bag          */
checked_fee(2, 45).   /* 2nd checked bag          */
checked_fee(3,150).   /* 3rd checked bag          */
checked_fee(N,200) :- N>=4.   /* 4th bag and beyond */

/* oversize fees – within U.S. / Canada / PR / USVI */
oversize_fee(Dim,30) :- Dim>62, Dim=<65.
oversize_fee(Dim,200) :- Dim>65, Dim=<115.
oversize_fee(Dim,0) :- Dim=<62.             /* not oversize */

/* overweight fees – within U.S. / Canada / PR / USVI */
overweight_fee(W,30)  :- W>50 , W=<53.
overweight_fee(W,100) :- W>53 , W=<70.
overweight_fee(W,200) :- W>70 , W=<100.
overweight_fee(W,0)   :- W=<50.

/* extra fee for a bag that is both oversize and/or overweight      */
/* “the higher fee … applies, in addition to the checked-bag fee.”  */
extra_fee(Dim,W,Fee) :-
    oversize_fee(Dim,OS),
    overweight_fee(W,OW),
    (OS>=OW -> Fee=OS ; Fee=OW).

/* ----------  Facts describing Sarah’s flight and bags  ---------- */

flight_ticket(180).
cabin(main_cabin).
route(domestic).           /* Orlando-Philadelphia inside U.S. */

/* bag(Id,Length,Width,Height,Weight) */
bag(1,22,13, 6, 10).    /* backpack – will be carry-on        */
bag(2,44,22,20, 69).
bag(3,34,18,12, 51).
bag(4,38,22,16, 84).
bag(5,38,14,11, 90).

/* ----------  Helper predicates  ---------- */

/* sum of the three dimensions */
dim_sum(Id,Sum) :- bag(Id,L,W,H,_), Sum is L+W+H.

/* does the bag fit the carry-on limits?  */
carry_on(Id) :-
    bag(Id,L,W,H,_),
    carry_on_max(MaxL,MaxW,MaxH),
    L=<MaxL, W=<MaxW, H=<MaxH.

/* checked bag ordering (exclude the single carry-on) */
checked_bag_number(Id,N) :-
    findall(B,(bag(B,_,_,_,_), \\+ carry_on(B)), Bs),
    nth1(N,Bs,Id).

/* fee for one checked bag (includes base checked fee plus extra) */
bag_total_fee(Id,Total) :-
    checked_bag_number(Id,N),
    checked_fee(N,Base),
    dim_sum(Id,Dim),
    bag(Id,_,_,_,W),
    extra_fee(Dim,W,Extra),
    Total is Base + Extra.

/* sum of all checked-bag fees */
total_checked_bag_fees(Sum) :-
    findall(F, (bag_total_fee(_,F)), Fs),
    sum_list(Fs,Sum).

/* ----------  Grand total (ticket + all luggage charges) ---------- */
total_cost(Total) :-
    flight_ticket(Tix),
    total_checked_bag_fees(Bags),
    Total is Tix + Bags.

/* ----------  Query and output ---------- */
:- total_cost(Total), format('Total cost: ~w~n',[Total]).
:- halt.

=============
Example 2:
% Text
% Thomas is a First Class passenger flying from Montreal to Portland with the following items: 1. A backpack: 19 x 11 x 7 inches, 6 lbs; 2. A luggage box: 36 x 22 x 14 inches, 55 lbs; 3. A luggage box: 37 x 18 x 9 inches, 80 lbs; 4. A backpack: 34 x 20 x 10 inches, 61 lbs; 5. A backpack: 36 x 20 x 9 inches, 95 lbs; 6. A backpack: 44 x 28 x 21 inches, 78 lbs; 7. A backpack: 33 x 20 x 10 inches, 83 lbs; 8. A luggage box: 38 x 16 x 9 inches, 68 lbs; 9. A luggage box: 34 x 21 x 9 inches, 99 lbs; 10. A backpack: 33 x 21 x 10 inches, 81 lbs; 11. A backpack: 44 x 31 x 21 inches, 72 lbs; Thomas's flight ticket is $235.

% Question
% What is the total cost (including the flight ticket fee, checked bag fees, cost of special needs) according to the policies for the passenger?

/* ----------  Facts describing the trip -------------------- */


/* ticket price */
flight_cost(235).


/* list of checked bags: bag(Id,Length,Width,Height,Weight). */
bag(2,36,22,14,55).
bag(3,37,18, 9,80).
bag(4,34,20,10,61).
bag(5,36,20, 9,95).
bag(6,44,28,21,78).
bag(7,33,20,10,83).
bag(8,38,16, 9,68).
bag(9,34,21, 9,99).
bag(10,33,21,10,81).
bag(11,44,31,21,72).


/* list (constant) of all checked-bag Ids */
checked_bag_ids([2,3,4,5,6,7,8,9,10,11]).


/* ----------  Statutory rules (for this itinerary) --------- */


/* sum of dimensions */
dims_sum(L,W,H,S) :- S is L+W+H.


/* oversize fee for: Within / between U.S. and Canada */
oversize_fee(Sum,Fee) :-
       (   Sum =< 62      -> Fee = 0
       ;   Sum =< 65      -> Fee = 30
       ;   Sum =< 115     -> Fee = 200 ).


/* overweight fee for: Within / between U.S. and Canada          */
/* Threshold is 50 lbs for CHARGED bags, 70 lbs for COMPLIMENTARY */
overweight_fee(W,Thresh,Fee) :-
       (   W =< Thresh        -> Fee = 0
       ;   W =< 53            -> Fee = 30
       ;   W =< 70            -> Fee = 100
       ;   W =< 100           -> Fee = 200 ).


/* penalty for a bag: higher of over-size vs over-weight */
penalty(BagId,comp,Pen) :-
       bag(BagId,L,W,H,Weight),
       dims_sum(L,W,H,Sum),
       oversize_fee(Sum,OS),
       overweight_fee(Weight,70,OW),         % complimentary ⇒ 70-lb limit
       Pen is max(OS,OW).


penalty(BagId,charged,Pen) :-
       bag(BagId,L,W,H,Weight),
       dims_sum(L,W,H,Sum),
       oversize_fee(Sum,OS),
       overweight_fee(Weight,50,OW),         % charged bag ⇒ 50-lb limit
       Pen is max(OS,OW).


/* checked-bag fee by ordinal position for First Class on this route */
bag_fee(1,0).
bag_fee(2,0).
bag_fee(3,150).
bag_fee(N,200) :- N>=4.


/* ----------  Helper predicates ---------------------------- */


/* choose 2 different elements (F1<F2) from a list */
choose_two(List,F1,F2) :-
       append(_,[F1|Tail],List),
       member(F2,Tail).


/* remove chosen freebies from the master list to build the ordered list */
ordered_list(F1,F2,Ordered) :-
       checked_bag_ids(All),
       select(F1,All,Rest1),
       select(F2,Rest1,Rest),
       Ordered = [F1,F2|Rest].          % freebies go in positions 1 and 2


/* compute cost for a particular choice of freebies */
cost_for_choice(F1,F2,Total) :-
       ordered_list(F1,F2,Ordered),
       cost_bags(Ordered,1,CostBags,Penalties),
       flight_cost(Flight),
       Total is Flight + CostBags + Penalties.


/* walk through ordered list accumulating bag fees and penalties */
cost_bags([],_,0,0).
cost_bags([Bag|Bs],Idx,CostSum,PenSum) :-
       (Idx =< 2 -> Type = comp ; Type = charged),
       bag_fee(Idx,Fee),
       penalty(Bag,Type,Pen),
       NextIdx is Idx+1,
       cost_bags(Bs,NextIdx,CostRest,PenRest),
       CostSum is Fee + CostRest,
       PenSum  is Pen + PenRest.


/* compute minimal total cost over all ways of selecting 2 complimentary bags */
total_cost(MinTotal) :-
       checked_bag_ids(L),
       findall(T,
               ( choose_two(L,F1,F2),
                 cost_for_choice(F1,F2,T)),
               Totals),
       min_list(Totals,MinTotal).


/* ----------  Run the query and print ----------------------- */
:- total_cost(Total), format('Total cost: ~w~n',[Total]).
:- halt.
```
"""

EXAMPLE_LEGAL_IR_ONE_SHOT = """
### HousingQA Sample 1
- state: Alabama
- focus_year: 2021

### Question
Is there a state/territory law regulating residential evictions?

### Natural Language Statutes
[1] ALA. CODE § 35-9A-141(11)
(11) "premises" means a dwelling unit and the structure of which it is a part and facilities and appurtenances therein and grounds, areas, and facilities held out for the use of tenants generally or whose use is promised by the rental agreement to the tenant;

Solution (Prolog):
```prolog
% HousingQA example: Alabama
state(alabama).

qa_item(
    alabama,
    "Is there a state/territory law regulating residential evictions?"
).

statute(ala_code_35_9a_141_11).
statute_of_state(ala_code_35_9a_141_11, alabama).
defines(ala_code_35_9a_141_11, premises).
includes_in_premises(ala_code_35_9a_141_11, dwelling_unit).
refers_to(ala_code_35_9a_141_11, tenant).
refers_to(ala_code_35_9a_141_11, rental_agreement).

residential_landlord_tenant_statute(Law) :-
    defines(Law, premises),
    includes_in_premises(Law, dwelling_unit),
    refers_to(Law, tenant),
    refers_to(Law, rental_agreement).

regulates_residential_evictions(Law) :-
    residential_landlord_tenant_statute(Law).

state_has_residential_eviction_law(State) :-
    statute_of_state(Law, State),
    regulates_residential_evictions(Law).

question_predicate(
    "Is there a state/territory law regulating residential evictions?",
    state_has_residential_eviction_law
).

derived_answer(yes) :-
    qa_item(State, Question),
    question_predicate(Question, Pred),
    Goal =.. [Pred, State],
    call(Goal), !.
derived_answer(no) :-
    qa_item(State, Question),
    question_predicate(Question, Pred),
    Goal =.. [Pred, State],
    \\+ call(Goal).

housing_answer(Result) :-
    derived_answer(Result).

main :-
    housing_answer(Result),
    format('housing_answer(~w).~n', [Result]).

:- initialization(main, main).
```
"""

EXAMPLE_LEGAL_IR_TWO_SHOT = EXAMPLE_LEGAL_IR_ONE_SHOT + """

------

### HousingQA Sample 2
- state: Oregon
- focus_year: 2021

### Question
In an eviction action, can a tenant rebut/raise the defense that the landlord accepted partial payment of rent?

### Natural Language Statutes
[1] OR. REV. STAT. § 90.370
(1)(a) In an action for possession based upon nonpayment of the rent or in an action for rent when the tenant is in possession, the tenant may counterclaim ...
(1)(b) ... if no rent remains due after application of this section ... a judgment shall be entered for the tenant in the action for possession.

[2] OR. REV. STAT. § 90.385
(1) Except as provided in this section, a landlord may not retaliate by increasing rent or decreasing services, by serving a notice to terminate the tenancy or by bringing or threatening to bring an action for possession after: ...

[3] OR. REV. STAT. § 90.390
(2) If the tenant can prove that the landlord violated subsection (1) of this section, the tenant has a defense in any discriminatory action brought by the landlord against the tenant for possession, unless the tenant is in default in rent.

[4] OR. REV. STAT. § 90.449
(1) A landlord may not terminate or fail to renew a tenancy, serve a notice to terminate a tenancy, bring or threaten to bring an action for possession, increase rent, decrease services or refuse to enter into a rental agreement: ...

[5] OR. REV. STAT. § 90.368
(2) If, contrary to ORS 90.320, the landlord fails to repair a minor habitability defect, the tenant may cause the repair ... not to exceed $300.

Solution (Prolog):
```prolog
% HousingQA example: Oregon
statute(ors_90_370).
statute(ors_90_385).
statute(ors_90_390).
statute(ors_90_449).
statute(ors_90_368).

tenant_defense_in_eviction(retaliation, ors_90_385).
tenant_defense_in_eviction(discrimination, ors_90_390).
tenant_defense_in_eviction(domestic_violence_status, ors_90_449).
tenant_may_repair_and_deduct(ors_90_368, minor_habitability_defect, landlord_failed_to_repair, maximum_deduction_dollars(300)).

defense_available_in_eviction(eviction_action, retaliation) :-
    tenant_defense_in_eviction(retaliation, ors_90_385).
defense_available_in_eviction(eviction_action, discrimination) :-
    tenant_defense_in_eviction(discrimination, ors_90_390).
defense_available_in_eviction(eviction_action, domestic_violence_status) :-
    tenant_defense_in_eviction(domestic_violence_status, ors_90_449).
defense_available_in_eviction(eviction_action, minor_habitability_repair_and_deduct) :-
    tenant_may_repair_and_deduct(ors_90_368, minor_habitability_defect, landlord_failed_to_repair, maximum_deduction_dollars(300)).

question_state(oregon).
question_scenario(eviction_action).
question_issue(landlord_accepted_partial_payment_of_rent).

can_tenant_raise_defense_partial_payment_in_eviction :-
    question_state(oregon),
    question_scenario(eviction_action),
    defense_available_in_eviction(eviction_action, partial_payment_accepted_by_landlord).

housing_answer(yes) :- can_tenant_raise_defense_partial_payment_in_eviction.
housing_answer(no) :- \\+ can_tenant_raise_defense_partial_payment_in_eviction.

main :-
    housing_answer(Result),
    format('housing_answer(~w).~n', [Result]).

:- initialization(main, main).
```
"""

DISCARDED_SARA_EXAMPLE=r"""
Example 1:
% Alice was paid $1200 in 2019 for services performed in jail. Alice was committed to jail from January 24, 2015 to May 5th, 2019. From May 5th 2019 to Dec 31st 2019, Alice was paid $5320 in remuneration. Alice takes the standard deduction.

% Question
% How much tax does Alice have to pay in 2019? 

```prolog
/* ─────────────────────────  STATUTORY RULES  ───────────────────────── */

/* ---- wages, gross-income, and taxable-income computations ---- */

% sumlist(List, Sum)  – simple deterministic list-sum helper
sumlist([],Acc,Acc).
sumlist([H|T],Acc0,Sum) :-
    Acc1 is Acc0 + H,
    sumlist(T,Acc1,Sum).

% gross_income(Person, Year, Gross)
gross_income(P,Y,GI) :-
    findall(Amt, wages(P,Y,Amt,_Source), L),
    sumlist(L,0,GI).

/* ---- filing-status rules ---- */

% default facts – no information indicates “no”
married(_P,_Y)       :- fail.          % no marriage facts supplied
surviving_spouse(_P,_Y) :- fail.       % none in this case
head_of_household(_P,_Y) :- fail.      % none in this case

status(P,Y,single) :-
    \+ married(P,Y),
    \+ surviving_spouse(P,Y),
    \+ head_of_household(P,Y).

/* ---- standard deduction (special 2018-2025 amounts) ---- */
standard_deduction(single,             _Y, 12000).
standard_deduction(head_of_household,  _Y, 18000).
standard_deduction(surviving_spouse,   _Y, 24000).
standard_deduction(married_joint,      _Y, 24000).
standard_deduction(married_separate,   _Y, 12000).

standard_deduction_for(P,Y,Ded) :-
    status(P,Y,S),
    standard_deduction(S,Y,Ded).

/* ---- taxable income ---- */
taxable_income(P,Y,TI) :-
    gross_income(P,Y,GI),
    standard_deduction_for(P,Y,SD),
    TI0 is GI - SD,
    ( TI0 > 0 -> TI = TI0 ; TI = 0 ).

/* ---- individual income-tax rates, §1(c) brackets ---- */
tax_single(TI,Tax) :-
    ( TI =< 22100 ->
        Tax is 0.15 * TI
    ; TI =< 53500 ->
        Tax is 3315 + 0.28 * (TI - 22100)
    ; TI =< 115000 ->
        Tax is 12107 + 0.31 * (TI - 53500)
    ; TI =< 250000 ->
        Tax is 31172 + 0.36 * (TI - 115000)
    ;   Tax is 79772 + 0.396 * (TI - 250000)
    ).
/* ---- top-level tax predicate ---- */
tax(P,Y,Tax) :-
    status(P,Y,single),            % the only possible status here
    taxable_income(P,Y,TI),
    tax_single(TI,Tax).
/* ─────────────────────────────  CASE FACTS  ───────────────────────────── */

% wages(Person, Year, Amount, SourceTag)
wages(alice, 2019, 1200, jail_service).
wages(alice, 2019, 5320, post_release_work).

/* ───────────────────────────────  QUERY  ─────────────────────────────── */

:- tax(alice, 2019, Tax), format('Tax result: ~w~n', [Tax]).
:- halt.
```
=============
"""

EXEMPLAR_SARA_V1 = """
Example 2:
% Text
% In 2017, Alice's gross income was $33200. Alice and Bob have been married since Feb 3rd, 2017. Alice has been blind since October 4, 2013. Alice and Bob file jointly in 2017. Bob has no gross income in 2017. Alice and Bob take the standard deduction. Alice and Bob has the same principal place of abode from 2017 to 2020.

% Question
% How much tax does Alice have to pay in 2017? 

```prolog
/* Facts from the case */
gross_income(alice, 2017, 33200).
gross_income(bob,   2017,     0).

blind(alice, 2017).

married(alice, bob, 2017).

joint_return(2017).

/* Basic amounts taken straight from the statutes              */
/* §63(c)(2)(A): 200% × $3,000 = $6,000 for MFJ basic standard */
base_standard_deduction_joint(6000).

/* §63(f): $600 per blind (or age-65) spouse on a joint return */
additional_standard_deduction(Year, Add) :-
    findall(600, (blind(Person, Year), married(Person, _, Year)), L),
    sum_list(L, Add).

/* Full standard deduction for this joint return               */
standard_deduction(Year, SD) :-
    joint_return(Year),
    base_standard_deduction_joint(Base),
    additional_standard_deduction(Year, Add),
    SD is Base + Add.

/* §151(d)(1): personal exemption amount                        */
personal_exemption_amount(2000).

/* Two spouses ⇒ two personal exemptions on a joint return      */
personal_exemptions(Year, Exempt) :-
    joint_return(Year),
    personal_exemption_amount(A),
    Exempt is A * 2.

/* Combine spouses’ gross income                                */
combined_gross_income(Year, GI) :-
    findall(I, gross_income(_, Year, I), L),
    sum_list(L, GI).

/* §63(b): taxable income = AGI – std-deduction – exemptions     */
taxable_income(Year, TI) :-
    combined_gross_income(Year, GI),
    standard_deduction(Year, SD),
    personal_exemptions(Year, PE),
    TI0 is GI - SD - PE,
    ( TI0 > 0 -> TI = TI0 ; TI = 0 ).

/* §1(a) MFJ rate schedule – only first bracket needed here      */
tax_bracket_joint(TI, Tax) :-
    TI =< 36900,
    Tax is TI * 0.15.

/* Total tax for the joint return                               */
tax_due(Year, Tax) :-
    taxable_income(Year, TI),
    tax_bracket_joint(TI, Tax).

/* Alias so the query can use the exact name asked for          */
tax("Alice", Year, Tax) :-
    tax(alice, Year, Tax).

tax(alice, Year, Tax) :-
    tax_due(Year, Tax).

/* Helper: sum elements of a list                               */
sum_list([], 0).
sum_list([H|T], Sum) :- sum_list(T, R), Sum is H + R.

/* Query required by the problem statement                      */
:- tax("Alice", 2017, Tax), format('Tax result: ~w~n', [Tax]).
:- halt.
```
"""

EXEMPLARS_V2 = """
Example 1:

% Text
% Alice was paid $1200 in 2019 for services performed in jail. Alice was committed to jail from January 24, 2015 to May 5th, 2019. From May 5th 2019 to Dec 31st 2019, Alice was paid $5320 in remuneration. Alice takes the standard deduction.

% Question
% How much tax does Alice have to pay in 2019?

% Facts
:- [statutes/prolog/init].
service_("services").
patient_("services","jail").
agent_("services","Alice").
start_("services","2019-01-01").
end_("services","2019-05-05").
payment_("Alice was paid $1200 in 2019 for services performed in jail").
agent_("Alice was paid $1200 in 2019 for services performed in jail","jail").
patient_("Alice was paid $1200 in 2019 for services performed in jail","Alice").
start_("Alice was paid $1200 in 2019 for services performed in jail","2019-05-05").
purpose_("Alice was paid $1200 in 2019 for services performed in jail","services").
amount_("Alice was paid $1200 in 2019 for services performed in jail",1200).
penal_institution_("jail").
agent_("jail","jail").
incarceration_("committed to jail").
agent_("committed to jail","Alice").
patient_("committed to jail","jail").
start_("committed to jail","2015-01-24").
end_("committed to jail","2019-05-05").
payment_("From May 5th 2019 to Dec 31st 2019, Alice was paid $5320 in remuneration").
patient_("From May 5th 2019 to Dec 31st 2019, Alice was paid $5320 in remuneration","Alice").
amount_("From May 5th 2019 to Dec 31st 2019, Alice was paid $5320 in remuneration",5320).
start_("From May 5th 2019 to Dec 31st 2019, Alice was paid $5320 in remuneration","2019-12-31").

% Test
:- tax("Alice",2019,Res), format('Tax result: ~w~n', [Res]).
:- halt.

=============
Example 2:

% Text
% Alice and Bob got married on Feb 3rd, 1992. Alice and Bob have a child, Charlie, born October 9th, 2000. Alice died on July 9th, 2014. From 2004 to 2019, Bob furnished 40% of the costs of maintaining the home where he and Charlie lived during that time. In 2013, Alice and Bob filed jointly, and took the standard deduction. In 2013, Alice earned $65400 and Bob earned $56400.

% Question
% How much tax does Alice have to pay in 2013?

% Facts
:- [statutes/prolog/init].
joint_return_("filed jointly").
agent_("filed jointly","Alice").
agent_("filed jointly","Bob").
start_("filed jointly","2013-01-01").
end_("filed jointly","2013-12-31").
marriage_("married").
agent_("married","Alice").
agent_("married","Bob").
start_("married","1992-02-03").
death_("died").
agent_("died","Alice").
start_("died","2014-07-09").
end_("died","2014-07-09").
son_("child").
agent_("child","Charlie").
patient_("child","Alice").
patient_("child","Bob").
start_("child","2000-10-09").
residence_("lived").
agent_("lived","Charlie").
agent_("lived","Bob").
patient_("lived","the home").
start_("lived","2004-01-01").
end_("lived","2019-12-31").
bob_household_maintenance(Year,Event,Start_day,End_day) :-
    between(2004,2019,Year),
    atom_concat("furnished 40% of the costs ",Year,Event),
    first_day_year(Year,Start_day),
    last_day_year(Year,End_day).
payment_(Event) :- bob_household_maintenance(_,Event,_,_).
agent_(Event,"Bob") :- bob_household_maintenance(_,Event,_,_).
amount_(Event,40) :- bob_household_maintenance(_,Event,_,_).
purpose_(Event,"the home") :- bob_household_maintenance(_,Event,_,_).
start_(Event,Start_day) :- bob_household_maintenance(_,Event,Start_day,_).
end_(Event,End_day) :- bob_household_maintenance(_,Event,_,End_day).
someone_household_maintenance(Year,Event,Start_day,End_day) :-
    between(2004,2019,Year),
    atom_concat("maintaining the home ",Year,Event),
    first_day_year(Year,Start_day),
    last_day_year(Year,End_day).
payment_(Event) :- someone_household_maintenance(_,Event,_,_).
agent_(Event,"someone") :- someone_household_maintenance(_,Event,_,_).
amount_(Event,60) :- someone_household_maintenance(_,Event,_,_).
purpose_(Event,"the home") :- someone_household_maintenance(_,Event,_,_).
start_(Event,Start_day) :- someone_household_maintenance(_,Event,Start_day,_).
end_(Event,End_day) :- someone_household_maintenance(_,Event,_,End_day).
income_("Alice earned").
agent_("Alice earned","Alice").
amount_("Alice earned",65400).
start_("Alice earned","2013-12-31").
income_("Bob earned").
agent_("Bob earned","Bob").
amount_("Bob earned",56400).
start_("Bob earned","2013-12-31").

% Test
:- tax("Alice",2013,Res), format('Tax result: ~w~n', [Res]).
:- halt.

=============
"""



EXEMPLARS_V3 = """
Example 1:

% Text
% Alice was paid $1200 in 2019 for services performed in jail. Alice was committed to jail from January 24, 2015 to May 5th, 2019. From May 5th 2019 to Dec 31st 2019, Alice was paid $5320 in remuneration. Alice takes the standard deduction.

% Question
% How much tax does Alice have to pay in 2019?

% Facts
:- [statutes/prolog/init].
payment_(span("paid",10,13)).
service_(span("services",33,40)).
penal_institution_(span("jail",55,58)).
incarceration_(span("committed",71,79)).
payment_(span("paid",175,178)).
agent_(span("committed",71,79),span("Alice",61,65)).
patient_(span("committed",71,79),span("jail",84,87)).
start_(span("committed",71,79),span(20150124,94,109)).
end_(span("committed",71,79),span(20190505,114,126)).
patient_(span("paid",10,13),span("Alice",0,4)).
amount_(span("paid",10,13),span(1200,16,19)).
purpose_(span("paid",10,13),span("services",33,40)).
agent_(span("paid",10,13),span("jail",55,58)).
start_(span("paid",10,13),span(20190101,24,27)).
start_(span("paid",175,178),span(20191231,150,162)).
patient_(span("paid",175,178),span("Alice",165,169)).
amount_(span("paid",175,178),span(5320,181,184)).
agent_(span("jail",84,87),span("jail",55,58)).
agent_(span("services",33,40),span("Alice",0,4)).
start_(span("services",33,40),span(20150124,94,109)).
patient_(span("services",33,40),span("jail",55,58)).
end_(span("services",33,40),span(20190505,114,126)).

% Test
:- tax("Alice",2019,Res), format('Tax result: ~w~n', [Res]).
:- halt.

=============
Example 2:
% Text
% Alice and Bob got married on Feb 3rd, 1992. Alice and Bob have a child, Charlie, born October 9th, 2000. Alice died on July 9th, 2014. From 2004 to 2019, Bob furnished 40% of the costs of maintaining the home where he and Charlie lived during that time. In 2013, Alice and Bob filed jointly, and took the standard deduction. In 2013, Alice earned $65400 and Bob earned $56400.

% Question
% How much tax does Alice have to pay in 2013?

% Facts
:- [statutes/prolog/init].
bob_household_maintenance(Year,Event,Start_day,End_day) :-
    between(2004,2019,Year),
    atom_concat("furnished 40% of the costs ",Year,Event_name),
    Event = span(Event_name,158,166),
    first_day_year(Year,Start_day),
    last_day_year(Year,End_day).
payment_(Event) :- bob_household_maintenance(_,Event,_,_).
agent_(Event,span("Bob",154,157)) :- bob_household_maintenance(_,Event,_,_).
amount_(Event,span(40,168,169)) :- bob_household_maintenance(_,Event,_,_).
purpose_(Event,span("home",204,207)) :- bob_household_maintenance(_,Event,_,_).
start_(Event,span(Start_day,140,143)) :- bob_household_maintenance(_,Event,Start_day,_).
end_(Event,span(End_day,148,151)) :- bob_household_maintenance(_,Event,_,End_day).
someone_household_maintenance(Year,Event,Start_day,End_day) :-
    between(2004,2019,Year),
    atom_concat("maintaining the home ",Year,Event_name),
    Event = span(Event_name,158,166),
    first_day_year(Year,Start_day),
    last_day_year(Year,End_day).
payment_(Event) :- someone_household_maintenance(_,Event,_,_).
agent_(Event,span("someone",154,157)) :- someone_household_maintenance(_,Event,_,_).
amount_(Event,span(60,168,169)) :- someone_household_maintenance(_,Event,_,_).
purpose_(Event,span("home",204,207)) :- someone_household_maintenance(_,Event,_,_).
start_(Event,span(Start_day,140,143)) :- someone_household_maintenance(_,Event,Start_day,_).
end_(Event,span(End_day,148,151)) :- someone_household_maintenance(_,Event,_,End_day).
marriage_(span("married",18,24)).
son_(span("child",65,69)).
death_(span("died",111,114)).
residence_(span("lived",230,234)).
joint_return_(span("jointly",283,289)).
income_(span("earned",340,345)).
income_(span("earned",362,367)).
agent_(span("died",111,114),span("Alice",105,109)).
start_(span("died",111,114),span(20140709,119,132)).
start_(span("earned",340,345),span(20130101,328,331)).
agent_(span("earned",340,345),span("Alice",334,338)).
amount_(span("earned",340,345),span(65400,348,352)).
start_(span("earned",362,367),span(20130101,328,331)).
agent_(span("earned",362,367),span("Bob",358,360)).
amount_(span("earned",362,367),span(56400,370,374)).
start_(span("jointly",283,289),span(20130101,257,260)).
agent_(span("jointly",283,289),span("Alice",263,267)).
agent_(span("jointly",283,289),span("Bob",273,275)).
agent_(span("married",18,24),span("Alice",0,4)).
agent_(span("married",18,24),span("Bob",10,12)).
start_(span("married",18,24),span(19920203,29,41)).
start_(span("lived",230,234),span(20040101,140,143)).
end_(span("lived",230,234),span(20191231,148,151)).
agent_(span("lived",230,234),span("Bob",154,156)).
patient_(span("lived",230,234),span("home",204,207)).
agent_(span("lived",230,234),span("Charlie",222,228)).
patient_(span("child",65,69),span("Alice",44,48)).
patient_(span("child",65,69),span("Bob",54,56)).
agent_(span("child",65,69),span("Charlie",72,78)).
start_(span("child",65,69),span(20001009,86,102)).
birth_(span("born",81,84)).
agent_(span("born",81,84),span("Charlie",72,78)).
start_(span("born",81,84),span(20001009,86,102)).

% Test
:- tax("Alice",2013,Res), format('Tax result: ~w~n', [Res]).
:- halt.

=============
"""


EXEMPLARS_V4 = """
% Text
% Alice was paid $1200 in 2019 for services performed in jail. Alice was committed to jail from January 24, 2015 to May 5th, 2019. From May 5th 2019 to Dec 31st 2019, Alice was paid $5320 in remuneration. Alice takes the standard deduction.

% Question
% How much tax does Alice have to pay in 2019?

% Facts
:- [statutes/prolog/init].
payment_(paid_0).
service_(services_0).
penal_institution_(jail_0).
incarceration_(committed_0).
payment_(paid_1).
agent_(committed_0,"Alice").
patient_(committed_0,"jail").
start_(committed_0,"2015-01-24").
end_(committed_0,"2019-05-05").
patient_(paid_0,"Alice").
amount_(paid_0,1200).
purpose_(paid_0,services_0).
agent_(paid_0,jail_0).
start_(paid_0,"2019-01-01").
start_(paid_1,"2019-12-31").
patient_(paid_1,"Alice").
amount_(paid_1,5320).
agent_("jail",jail_0).
agent_(services_0,"Alice").
start_(services_0,"2015-01-24").
patient_(services_0,jail_0).
end_(services_0,"2019-05-05").

% Test
:- tax("Alice",2019,Res), format('Tax result: ~w~n', [Res]).
:- halt.

% Text
% Alice and Bob got married on Feb 3rd, 1992. Alice and Bob have a child, Charlie, born October 9th, 2000. Alice died on July 9th, 2014. From 2004 to 2019, Bob furnished 40% of the costs of maintaining the home where he and Charlie lived during that time. In 2013, Alice and Bob filed jointly, and took the standard deduction. In 2013, Alice earned $65400 and Bob earned $56400.

% Question
% How much tax does Alice have to pay in 2013?

% Facts
:- [statutes/prolog/init].
marriage_(married_0).
son_(child_0).
death_(died_0).
residence_(lived_0).
joint_return_(jointly_0).
income_(earned_0).
income_(earned_1).
agent_(died_0,"Alice").
start_(died_0,"2014-07-09").
end_(died_0,"2014-07-09").
start_(earned_0,"2013-01-01").
agent_(earned_0,"Alice").
amount_(earned_0,65400).
start_(earned_1,"2013-01-01").
agent_(earned_1,"Bob").
amount_(earned_1,56400).
start_(jointly_0,"2013-01-01").
end_(jointly_0,"2013-12-31").
agent_(jointly_0,"Alice").
agent_(jointly_0,"Bob").
agent_(married_0,"Alice").
agent_(married_0,"Bob").
start_(married_0,"1992-02-03").
start_(lived_0,"2004-01-01").
end_(lived_0,"2019-12-31").
agent_(lived_0,"Bob").
patient_(lived_0,"home").
agent_(lived_0,"Charlie").
patient_(child_0,"Alice").
patient_(child_0,"Bob").
agent_(child_0,"Charlie").
start_(child_0,"2000-10-09").
bob_household_maintenance(Year,Event,Start_day,End_day) :-
    between(2004,2019,Year),
    atom_concat("furnished 40% of the costs ",Year,Event_name),
    Event = Event_name,
    first_day_year(Year,Start_day),
    last_day_year(Year,End_day).
payment_(Event) :- bob_household_maintenance(_,Event,_,_).
agent_(Event,"Bob") :- bob_household_maintenance(_,Event,_,_).
amount_(Event,40) :- bob_household_maintenance(_,Event,_,_).
purpose_(Event,"home") :- bob_household_maintenance(_,Event,_,_).
start_(Event,Start_day) :- bob_household_maintenance(_,Event,Start_day,_).
end_(Event,End_day) :- bob_household_maintenance(_,Event,_,End_day).
someone_household_maintenance(Year,Event,Start_day,End_day) :-
    between(2004,2019,Year),
    atom_concat("maintaining the home ",Year,Event_name),
    Event = Event_name,
    first_day_year(Year,Start_day),
    last_day_year(Year,End_day).
payment_(Event) :- someone_household_maintenance(_,Event,_,_).
agent_(Event,"someone") :- someone_household_maintenance(_,Event,_,_).
amount_(Event,60) :- someone_household_maintenance(_,Event,_,_).
purpose_(Event,"home") :- someone_household_maintenance(_,Event,_,_).
start_(Event,Start_day) :- someone_household_maintenance(_,Event,Start_day,_).
end_(Event,End_day) :- someone_household_maintenance(_,Event,_,End_day).

% Test
:- tax("Alice",2013,Res), format('Tax result: ~w~n', [Res]).

:- halt.
"""

EXEMPLAR_SARA_BINARY = """
Example 1:

% Text
% Alice is married under section 7703 for the year 2017. Alice's taxable income for the year 2017 is $554313. Alice files a separate return.

% Claim
% Alice has to pay $207772 in taxes for the year 2017 under section 1(d).

% Answer: Entailment

```prolog
/* ---------- Statutory rules (excerpts) ---------- */

/* Tax computation under section 1(d) - married individual filing a separate return */
tax_section_1d(TI, Tax) :-
    ( TI =< 18450 ->
        Tax is 0.15 * TI
    ; TI =< 44575 ->
        Tax is 2767.50 + 0.28 * (TI - 18450)
    ; TI =< 70000 ->
        Tax is 10082.50 + 0.31 * (TI - 44575)
    ; TI =< 125000 ->
        Tax is 17964.25 + 0.36 * (TI - 70000)
    ;
        Tax is 37764.25 + 0.396 * (TI - 125000)
    ).

/* ---------- Facts for the case ---------- */

taxable_income(alice, 554313).
married_under_7703(alice).
files_separate_return(alice).

/* ---------- Derivation of Alice's tax liability ---------- */

alice_tax(Tax) :-
    taxable_income(alice, TI),
    married_under_7703(alice),
    files_separate_return(alice),
    tax_section_1d(TI, Tax).

/* ---------- Verification of the claim ---------- */

:- (  alice_tax(Tax),
      round(Tax, Rounded),
      Rounded =:= 207772
   -> format('Result: Entailment~n')
   ;  format('Result: Contradiction~n')
   ).
:- halt.
```
=============
"""

EXAMPLE_USCIS_ONE_SHOT = r"""
## USCIS Sample

### Input
You are an expert in the analysis of immigration appeals and you will parse these Administrative Appeals Office cases into Prolog Code.
Parse the facts and rules into Prolog code, ensuring that the program's output is binary: either Dismissed or Accepted.
You are given the following facts:
The petitioner is a native and citizen of Guatemala who held U-2 nonimmigrant status from May 2017 until May 2021. She timely filed Form I-485 to adjust status as a derivative U nonimmigrant in March 2021 seeking lawful permanent resident status. The Vermont Service Center director denied her I-485, stating she had not submitted a completed Form I-693, Report of Immigration Medical Examination and Vaccination Record. The petitioner appealed that denial and, on appeal, submitted a newly executed Form I-693 medical examination.

You are given the following rules:
Section 245(m) of the Act contains the eligibility requirements for individuals seeking to adjust status to that of a lawful permanent resident (LPR) based on having been granted U nonimmigrant status. In addition, an applicant for adjustment of status under 245(m) must comply with the general eligibility and documentary requirements to adjust status at 8 C.F.R. § 245 .5, which requires that the applicant"have a medical examination by a designated civil surgeon, whose report setting forth the findings of the mental and physical condition of the applicant, including compliance with section 212(a)(l)(A)(ii) of the Act, shall be incorporated into the record."

For true/false or yes/no predicates, use arity 0 and check it is consistent for all clauses. For example, use there_is_evidence. instead of there_is_evidence(True).
Output format contract:
- Return exactly one runnable fenced Prolog block.
- When executed, print exactly one final token: Accepted or Dismissed.
- Do not print labels/metadata such as "Label:", confidence values, or explanations.
Indicate your prolog code using:
```prolog
<YOUR_LOGIC_PROGRAM_HERE>
```
Do not include the query in the prolog output, only include the entrypoint.
Include this structure at the end and work assuming that eligibility_met is all the conditions necessary to Accept the case. Therefore, this must be the last part of the program.
```prolog
decision(Result) :-
    (   eligibility_met
    ->  Result = 'Accepted'
    ;   Result = 'Dismissed'
    ).

 main :-
    catch(
        (   decision(Result),
            writeln(Result)
        ),
        error(existence_error(procedure, PI), _),
        handle_undefined(PI)
    ).

handle_undefined(Name/Arity) :-
    (   current_predicate(Name/OtherArity),
        OtherArity \= Arity
    ->  format('Programming error: called ~w/~w, but only ~w/~w is defined.~n',
               [Name, Arity, Name, OtherArity])
    ;   format('Lack of information: predicate ~w/~w is not defined.~n',
               [Name, Arity])
    ).

:- initialization(main, main).
```

Solution (Prolog):
```prolog
% Facts (zero-arity predicates for yes/no style facts)
petitioner_from_guatemala.
held_u2_from_may_2017_until_may_2021.
filed_i485_march_2021.
timely_filed.
derivative_u_status.
director_denied_for_missing_i693.
appealed.
submitted_i693_on_appeal.
i693_executed_by_designated_civil_surgeon.
i693_includes_vaccination_compliance.

% Legal-rule facts (expressing applicability of statutory/regulatory requirements)
section_245m_applicable.
cfr_8_245_5_requires_medical.
general_documentary_requirements_met.

% Derived predicates (zero-arity as required)
was_u_nonimmigrant_and_derivative_at_filing :-
    derivative_u_status,
    timely_filed.

medical_exam_valid :-
    submitted_i693_on_appeal,
    i693_executed_by_designated_civil_surgeon,
    i693_includes_vaccination_compliance.

% eligibility_met must represent all conditions necessary to Accept the case
eligibility_met :-
    section_245m_applicable,
    cfr_8_245_5_requires_medical,
    was_u_nonimmigrant_and_derivative_at_filing,
    medical_exam_valid,
    general_documentary_requirements_met.

decision(Result) :-
    (   eligibility_met
    ->  Result = 'Accepted'
    ;   Result = 'Dismissed'
    ).

main :-
    catch(
        (   decision(Result),
            writeln(Result)
        ),
        error(existence_error(procedure, PI), _),
        handle_undefined(PI)
    ).

handle_undefined(Name/Arity) :-
    (   current_predicate(Name/OtherArity),
        OtherArity \= Arity
    ->  format('Programming error: called ~w/~w, but only ~w/~w is defined.~n',
               [Name, Arity, Name, OtherArity])
    ;   format('Lack of information: predicate ~w/~w is not defined.~n',
               [Name, Arity])
    ).

:- initialization(main, main).
```
"""
