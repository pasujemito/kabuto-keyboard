#include "../src/stats_logic.h"
#include <cassert>
#include <iostream>
#include <string>
int main(){
    // No rate until a minute of readings; then tenths of a percent per hour.
    XpTracker t;assert(t.perHour()==-1&&t.minutesToLevel()==-1);
    t.add(200,0);t.add(250,30000);assert(t.perHour()==-1);
    t.add(300,60000);assert(t.perHour()==6000);              // +10% in a minute = 600%/h
    assert(t.minutesToLevel()==7);                            // 70% left at 600%/h
    // A level-up (95% -> 3%), once it has held 10 s, counts a level and starts the rate
    // afresh for the new level: nothing to show until a minute into it, then only what
    // was gained since.
    XpTracker w;w.add(900,0);w.add(950,60000);assert(w.perHour()==3000);
    w.add(30,90000);w.add(31,95000);assert(w.levels==0&&w.lastXp==950);   // not yet: it must hold
    w.add(30,100000);assert(w.levels==1&&w.gained==0&&w.lastXp==30&&w.perHour()==-1&&w.minutesToLevel()==-1);
    w.add(60,130000);assert(w.perHour()==-1);                 // 30 s into the new level
    w.add(90,160000);assert(w.perHour()==3600&&w.levels==1);  // +6% in its first minute = 360%/h
    w.add(5,170000);w.add(5,180000);assert(w.levels==1&&w.gained==6*10&&w.lastXp==5);   // a drop from 9%: not a level (death)
    // A small drop (death) adds nothing and isn't a level; what's gained after it counts.
    XpTracker d;d.add(500,0);d.add(450,30000);d.add(470,60000);assert(d.levels==0&&d.gained==20&&d.lastXp==470);
    // Changing maps: the bar misread low as the screen fades, then right again. No
    // level-up, no gain, and the rate stays what it was (it once went to 1000s %/h).
    XpTracker m;m.add(320,0);m.add(330,60000);assert(m.perHour()==600);
    m.add(40,60500);m.add(15,61000);m.add(0,61500);m.add(0,62000);m.add(250,62500);m.add(330,63000);m.add(331,64000);
    assert(m.levels==0&&m.gained==11&&m.lastXp==331&&m.perHour()==618);
    // ...even when a long load reads 0% for 30 s: from 33% that can't be a level-up or a death.
    for(uint32_t t=65000;t<95000;t+=500)m.add(0,t);
    m.add(332,95500);assert(m.levels==0&&m.gained==12&&m.lastXp==332);
    // Another character (a drop no game event makes, kept for a minute): afresh, no level.
    XpTracker other;other.add(600,0);for(uint32_t t=1000;t<=61000;t+=1000)other.add(300,t);
    assert(other.levels==0&&other.lastXp==300&&other.gained==0&&other.startMs==61000);
    // A misread high for a moment isn't gained; a big rise that holds (a quest) is.
    XpTracker q;q.add(300,0);q.add(980,500);q.add(305,1000);assert(q.gained==5&&q.lastXp==305);
    q.add(600,2000);q.add(605,12000);assert(q.gained==305&&q.lastXp==605&&q.levels==0);
    // Out-of-range readings are ignored.
    XpTracker o;o.add(-1,0);o.add(1001,0);assert(o.lastXp==-1);
    // Clock wraparound keeps the elapsed time right.
    XpTracker c;c.add(100,0xFFFF0000u);c.add(200,0xFFFF0000u+120000u);assert(c.perHour()==3000);
    // Live potions: threshold in whole percent, readings in tenths.
    assert(liveDecides(50,true)&&!liveDecides(0,true)&&!liveDecides(50,false));
    assert(liveWantsPotion(50,499,false,0)&&!liveWantsPotion(50,500,false,0)&&!liveWantsPotion(50,-1,false,0));
    assert(!liveWantsPotion(50,100,true,LIVE_POTION_GAP_MS-1)&&liveWantsPotion(50,100,true,LIVE_POTION_GAP_MS));
    // Real amounts: taps that fill the gap without waste, at least 1, at most 10; 0 = not set.
    assert(livePotionTaps(400,5000,800)==3);      // 3000 missing / 800 = 3 (a 4th would waste 200)
    assert(livePotionTaps(450,5000,4000)==1);     // one big potion: still drinks once below the threshold
    assert(livePotionTaps(0,100000,100)==LIVE_POTION_MAX_TAPS&&livePotionTaps(400,0,800)==0&&livePotionTaps(400,5000,0)==0&&livePotionTaps(-1,5000,800)==0);
    assert(livePotionTaps(1000,10000000,1)==1);   // full bar (no overflow on big totals)
    // Game state: anything but OK names a stop reason.
    assert(!liveStopReason(LIVE_OK)&&std::string(liveStopReason(LIVE_DEAD))=="you died"&&liveStopReason(LIVE_OFFLINE)&&liveStopReason(LIVE_TEST));
    assert(std::string(liveStateName(LIVE_TEST))=="test"&&std::string(liveStateName(LIVE_OFFLINE))=="offline"&&std::string(liveStateName(99))=="ok");
    // Notifications: a turn to a stop state is noted once (not each reading).
    {
        Notices n;
        assert(!n.note(LIVE_OK,LIVE_OK,10)&&n.count==0&&n.last==0);
        assert(n.note(LIVE_TEST,LIVE_OK,20)&&!n.note(LIVE_TEST,LIVE_TEST,30)&&n.count==1&&n.kind[0]==LIVE_TEST&&n.at[0]==20&&n.id(0)==1);
        assert(n.note(LIVE_DEAD,LIVE_TEST,40)&&n.count==2&&n.id(1)==2&&!n.note(99,LIVE_OK,50));   // test, then died: both
        for(uint32_t t=0;t<10;++t)n.note(t%2?LIVE_OFFLINE:LIVE_TEST,LIVE_OK,100+t);
        assert(n.count==Notices::CAP&&n.last==12&&n.id(0)==5&&n.id(Notices::CAP-1)==12&&n.at[0]==102&&n.kind[Notices::CAP-1]==LIVE_OFFLINE);   // the newest 8
        n.clear();assert(n.count==0&&n.note(LIVE_TEST,LIVE_OK,200)&&n.id(0)==13);   // ids go on counting
    }
    // Facing: map edges first, then mobs on one side only; stale data has no opinion.
    assert(liveFacing(true,50,120,true,MOB_LEFT)==1);      // near the left edge: face right, even with a mob left
    assert(liveFacing(true,950,120,true,MOB_RIGHT)==-1);   // near the right edge
    assert(liveFacing(true,500,120,true,MOB_LEFT)==-1&&liveFacing(true,500,120,true,MOB_RIGHT)==1);
    assert(liveFacing(true,500,120,true,MOB_LEFT|MOB_RIGHT)==-1&&liveFacing(true,500,120,true,MOB_LEFT|MOB_RIGHT|MOB_RIGHT_NEARER)==1);   // both: the nearer
    assert(liveFacing(true,500,120,true,0)==0&&liveFacing(true,50,120,true,MOB_LEFT|MOB_RIGHT|MOB_RIGHT_NEARER)==1);
    assert(liveFacing(true,500,120,false,MOB_LEFT)==0&&liveFacing(true,50,0,true,0)==0);   // features off
    assert(liveFacing(true,-1,120,true,0)==0&&liveFacing(false,50,120,true,MOB_LEFT)==0);   // no position / stale
    // Smart mode: attack with mobs, wait without; walk home when drifted (range 100).
    const uint8_t none=MOB_READ,left=MOB_READ|MOB_LEFT;
    assert(smartAction(true,left,true,500,true,500,100,false)==SMART_ATTACK&&smartAction(true,none,true,500,true,500,100,false)==SMART_WAIT);
    // Can't see mobs (no detector on this map / no fresh readings): stands still, never attacks blindly.
    assert(smartAction(true,0,true,500,true,500,100,false)==SMART_NO_DETECTOR&&smartAction(false,none,true,900,true,500,100,false)==SMART_NO_READINGS);
    assert(smartAction(false,left,true,500,true,500,100,false)==SMART_NO_READINGS);   // a stale "mob in reach" isn't trusted either
    assert(smartAction(true,none,true,650,true,500,100,false)==SMART_WALK_LEFT&&smartAction(true,none,true,-200,true,-50,100,false)==SMART_WALK_RIGHT);
    assert(smartAction(true,left,true,650,true,500,100,false)==SMART_ATTACK&&smartAction(true,left,true,750,true,500,100,false)==SMART_WALK_LEFT);   // mobs keep you, unless far
    // Nothing to fight: back home, to hunt around it. Walks when over HOME_SETTLE (6%) away, until within half that.
    assert(smartAction(true,none,true,560,true,500,100,false)==SMART_WAIT&&smartAction(true,none,true,570,true,500,100,false)==SMART_WALK_LEFT);
    {   // Home on its own (Smart off): only walking back, never waiting
        SmartInput h;h.fresh=true;h.mobs=MOB_READ;h.havePos=true;h.haveHome=true;h.home=500;h.range=100;
        h.pos=560;assert(homeDecide(h)==SMART_ATTACK);                 // within range, nothing in reach: attacks (Smart would wait)
        h.pos=650;assert(homeDecide(h)==SMART_WALK_LEFT);h.pos=350;assert(homeDecide(h)==SMART_WALK_RIGHT);
        h.pos=650;h.mobs=MOB_READ|MOB_LEFT;assert(homeDecide(h)==SMART_ATTACK);   // a mob in reach keeps you...
        h.pos=750;assert(homeDecide(h)==SMART_WALK_LEFT);                          // ...unless twice the range away
        h.pos=560;h.mobs=MOB_READ;h.homing=true;assert(homeDecide(h)==SMART_WALK_LEFT);   // walking: on to half the range
        h.range=0;h.pos=900;assert(homeDecide(h)==SMART_ATTACK);h.range=100;h.fresh=false;assert(homeDecide(h)==SMART_ATTACK);
    }
    assert(smartAction(true,none,true,540,true,500,100,true)==SMART_WALK_LEFT&&smartAction(true,none,true,525,true,500,100,true)==SMART_WAIT);
    assert(smartAction(true,none,true,420,true,500,100,false)==SMART_WALK_RIGHT);           // either side
    assert(smartAction(true,left,true,570,true,500,100,false)==SMART_ATTACK);               // mobs in reach: fight them first
    assert(smartAction(true,0,true,570,true,500,100,false)==SMART_NO_DETECTOR);             // no mob detector: can't tell, stand still
    assert(smartAction(true,none,true,900,true,500,0,false)==SMART_WAIT&&smartAction(true,none,false,0,true,500,100,false)==SMART_WAIT);   // no home / no position
    // With mobs in sight (counts and distances): approach walks to the nearer
    // side's mobs when none are in reach, but not past 3/4 of the home range;
    // auto-pause waits whatever's in reach; home still comes first.
    SmartInput in;in.fresh=true;in.mobs=none;in.seenLeft=1;in.seenRight=2;in.nearLeft=180;in.nearRight=150;
    in.havePos=in.haveHome=true;in.pos=500;in.home=500;in.range=100;
    assert(smartDecide(in)==SMART_WAIT);                                   // approach off: as before
    in.approach=true;assert(smartDecide(in)==SMART_APPROACH_RIGHT);
    in.nearLeft=120;assert(smartDecide(in)==SMART_APPROACH_LEFT);          // the nearer side
    in.pos=420;assert(smartDecide(in)==SMART_WALK_RIGHT);                  // 80 left of home (past 75): no further left, back home
    in.pos=500;in.seenLeft=0;in.nearLeft=-1;assert(smartDecide(in)==SMART_APPROACH_RIGHT);
    in.seenRight=0;in.nearRight=-1;assert(smartDecide(in)==SMART_WAIT);   // none in sight
    in.seenRight=2;in.nearRight=150;in.mobs=MOB_READ|MOB_RIGHT;assert(smartDecide(in)==SMART_ATTACK);   // in reach: attack
    in.paused=true;assert(smartDecide(in)==SMART_PAUSE);
    in.mobs=none;in.pos=580;assert(smartDecide(in)==SMART_WALK_LEFT);     // auto-pause: waits at home, not where it was
    in.pos=540;assert(smartDecide(in)==SMART_PAUSE);in.pos=500;in.mobs=MOB_READ|MOB_RIGHT;
    in.pos=700;in.mobs=none;assert(smartDecide(in)==SMART_WALK_LEFT);     // drifted: home before pausing
    in.pos=500;in.paused=false;in.seenLeft=in.seenRight=-1;assert(smartDecide(in)==SMART_WAIT);   // no counts: as before
    in.haveHome=false;in.seenRight=1;in.nearRight=300;assert(smartDecide(in)==SMART_APPROACH_RIGHT);   // no home: no limit
    // 1.18.6's "home" button still loads (saved buttons keep working), though nothing uses it now.
    assert(toolKeyFromName("home")==TOOL_HOME&&std::string(toolKeyName(TOOL_HOME))=="home");
    // Auto-pause at 30%: 6 seen sets the bar; 1 left (under 1.8) pauses, 4
    // (60%+) resumes; a pause lasts at most AUTO_PAUSE_MAX_MS, then the
    // stragglers are fought until the mobs are back.
    AutoPause ap;assert(!ap.update(6,300,0)&&ap.peak==6);
    assert(!ap.update(2,300,1000)&&ap.update(1,300,2000)&&ap.update(3,300,3000)&&!ap.update(4,300,4000));
    assert(ap.update(1,300,5000)&&ap.update(0,300,6000));                 // none left: still waiting for respawn
    assert(!ap.update(1,300,5000+AUTO_PAUSE_MAX_MS)&&ap.spent&&!ap.update(1,300,6000+AUTO_PAUSE_MAX_MS));
    assert(!ap.update(5,300,7000+AUTO_PAUSE_MAX_MS)&&ap.update(1,300,8000+AUTO_PAUSE_MAX_MS));   // back: pauses again
    assert(!ap.update(-1,300,9000+AUTO_PAUSE_MAX_MS)&&!ap.update(1,0,9000+AUTO_PAUSE_MAX_MS));     // not read / off
    AutoPause decay;decay.update(6,300,0);decay.update(2,300,MOB_PEAK_DECAY_MS);assert(decay.peak==5);   // one crowded moment fades
    AutoPause few;assert(!few.update(2,300,0)&&!few.update(0,300,1000)&&!few.update(1,300,2000));      // 2 at most: 1 left is half
    // Stuck: still for the window -> 1 (turn), still again -> 2 (stop); moving resets.
    StuckWatch sw;assert(sw.update(true,500,500,0,10000)==0&&sw.update(true,505,498,9999,10000)==0);
    assert(sw.update(true,505,498,10000,10000)==1&&sw.update(true,500,500,15000,10000)==0&&sw.update(true,500,500,20000,10000)==2);
    assert(sw.update(true,600,500,21000,10000)==0&&sw.strikes==0);   // moved away: fine again
    assert(sw.update(false,0,0,40000,10000)==0&&!sw.has);           // position lost: start over
    StuckWatch far;assert(far.update(true,-2400,1300,0,10000)==0&&far.update(true,-2395,1300,10000,10000)==1);   // map positions past the minimap's edges work too
    // Readings: Wi-Fi and USB share one parser; blanks and junk are "not read".
    assert(statsTenths("72.5")==725&&statsTenths("0")==0&&statsTenths("100")==1000);
    assert(statsTenths("")==-1&&statsTenths(nullptr)==-1&&statsTenths("abc")==-1&&statsTenths("7x")==-1&&statsTenths("101")==-1&&statsTenths("-1")==-1&&statsTenths("nan")==-1);
    assert(statsState("dead")==LIVE_DEAD&&statsState("offline")==LIVE_OFFLINE&&statsState("test")==LIVE_TEST&&statsState("map")==LIVE_OK&&statsState("ok")==LIVE_OK&&statsState("??")==LIVE_OK);
    assert(statsMobs("LR")==(MOB_READ|MOB_LEFT|MOB_RIGHT)&&statsMobs("RL")==(MOB_READ|MOB_LEFT|MOB_RIGHT|MOB_RIGHT_NEARER));
    assert(statsMobs("R")==(MOB_READ|MOB_RIGHT)&&statsMobs("")==MOB_READ&&statsMobs(nullptr)==0);   // empty = looked, none; absent = not looking
    assert(statsPos("1415")==1415&&statsPos("-250")==-250&&statsPos("0")==0&&statsPos("100000")==100000);
    assert(statsPos("")==LIVE_NO_POS&&statsPos(nullptr)==LIVE_NO_POS&&statsPos("12.5")==LIVE_NO_POS&&statsPos("x")==LIVE_NO_POS&&statsPos("100001")==LIVE_NO_POS);
    StatsReading r=parseStatsForm("hp=72.0&xp=63.2&x=41.5&y=70.0&wx=-1585&wy=740&state=dead&mobs=L");
    assert(r.hp==720&&r.mana==-1&&r.xp==632&&r.x==415&&r.y==700&&r.wx==-1585&&r.wy==740&&r.state==LIVE_DEAD&&r.mobs==(MOB_READ|MOB_LEFT));
    r=parseStatsForm("hp=&mana=40.0&state=ok&mobs=&junk=1&averyveryverylongkey=5&hp2=9");
    assert(r.hp==-1&&r.mana==400&&r.state==LIVE_OK&&r.mobs==MOB_READ&&r.x==-1&&r.wx==LIVE_NO_POS);
    assert(parseStatsForm("hp=50").mobs==0);   // no mob detector
    r=parseStatsForm("");assert(r.hp==-1&&r.state==LIVE_OK);
    r=parseStatsForm("hp=12345678901234567890&mana");assert(r.hp==-1&&r.mana==-1);   // oversized value, no '='
    // Mobs in sight, the nearest's name and the map's.
    r=parseStatsForm("hp=50&mobs=R&ml=1&mr=3&dl=192&dr=52&mn=Blue_Snail&map=Henesys_Hunting_Groun");
    assert(r.ml==1&&r.mr==3&&r.dl==192&&r.dr==52&&std::string(r.mob)=="Blue_Snail"&&std::string(r.map)=="Henesys_Hunting_Groun");
    r=parseStatsForm("hp=50");assert(r.ml==-1&&r.dr==-1&&!r.mob[0]&&!r.map[0]);   // not sent
    assert(statsCount("0")==0&&statsCount("9999")==9999&&statsCount("10000")==-1&&statsCount("-1")==-1&&statsCount("2.5")==-1&&statsCount("")==-1);
    char name[LIVE_NAME_LEN];statsName("Ma<p> 1-x_y",name);assert(std::string(name)=="Map1-x_y");
    statsName("abcdefghijklmnopqrstuvwxyz",name);assert(std::string(name)=="abcdefghijklmnopqrstuvw");   // 23 at most
    statsName(nullptr,name);assert(!name[0]);
    r=parseStatsForm("map=-");assert(std::string(r.map)=="-");   // a map the script wasn't taught
    // Screen reader keys pressed on the pad: names both ways, oldest first,
    // stale ones dropped, the oldest pushed out when full.
    assert(toolKeyFromName("mark")==TOOL_MARK&&toolKeyFromName("hide")==TOOL_HIDE&&toolKeyFromName("f8")==TOOL_NONE&&toolKeyFromName(nullptr)==TOOL_NONE);
    assert(std::string(toolKeyName(TOOL_OUTLINES))=="outlines"&&std::string(toolKeyName(99))=="");
    assert(toolKeyFromName("looser")==TOOL_LOOSER&&toolKeyFromName("stricter")==TOOL_STRICTER&&std::string(toolKeyName(TOOL_STRICTER))=="stricter");
    assert(toolKeyFromName("area")==TOOL_AREA&&std::string(toolKeyName(TOOL_AREA))=="area");
    {   // home, told back with each reading
        char f[48];
        homeReplyForm(f,sizeof(f),true,true,1415,true,500);assert(std::string(f)=="home=1415&hm=1&hr=500");
        homeReplyForm(f,sizeof(f),true,true,-30,false,0);assert(std::string(f)=="home=-30&hm=0&hr=0");
        homeReplyForm(f,sizeof(f),true,false,1415,true,500);assert(!f[0]);   // no home yet
        homeReplyForm(f,sizeof(f),false,true,1415,true,500);assert(!f[0]);   // nothing playing
    }
    ToolKeys tk;char out[64];tk.take(0,out,sizeof(out));assert(!out[0]);
    tk.push(TOOL_MARK,1000);tk.push(TOOL_SKIP,4500);tk.push(TOOL_MAP,5000);tk.take(5000,out,sizeof(out));
    assert(std::string(out)=="skip,map"&&tk.count==0);   // the mark is 4 s old
    for(int i=0;i<10;++i)tk.push(i%2?TOOL_HIDE:TOOL_MARK,100);
    tk.take(100,out,sizeof(out));assert(std::string(out)=="mark,hide,mark,hide,mark,hide,mark,hide");   // 8 kept
    tk.push(TOOL_OUTLINES,0);tk.take(0,out,8);assert(!out[0]);   // doesn't fit: nothing half written
    std::cout<<"stats logic tests passed\n";
}
