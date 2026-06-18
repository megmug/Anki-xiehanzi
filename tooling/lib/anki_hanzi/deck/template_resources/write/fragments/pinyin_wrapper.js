  // https://github.com/krmanik/colorize-pinyin
  function pinyinWrapper() {
    const n = ["t0", "t1", "t2", "t3", "t4"],
      i = [
        [6, "zhuang,shuang,chuang".split(",")],
        [
          5,
          "zhuan,zhuai,zhong,zheng,zhang,xiong,xiang,shuan,shuai,sheng,shang,qiong,qiang,niang,liang,kuang,jiong,jiang,huang,guang,chuan,chuai,chong,cheng,chang".split(
            ",",
          ),
        ],
        [
          4,
          "zuan,zong,zhuo,zhun,zhui,zhua,zhou,zhen,zhei,zhao,zhan,zhai,zeng,zang,yuan,yong,ying,yang,xuan,xing,xiao,xian,weng,wang,tuan,tong,ting,tiao,tian,teng,tang,suan,song,shuo,shun,shui,shua,shou,shen,shei,shao,shan,shai,seng,sang,ruan,rong,reng,rang,quan,qing,qiao,qian,ping,piao,pian,peng,pang,nüe,nuan,nong,ning,niao,nian,neng,nang,ming,miao,mian,meng,mang,lüe,luan,long,ling,liao,lian,leng,lang,kuan,kuai,kong,keng,kang,juan,jing,jiao,jian,huan,huai,hong,heng,hang,guan,guai,gong,geng,gang,feng,fang,duan,dong,ding,diao,dian,deng,dang,cuan,cong,chuo,chun,chui,chua,chou,chen,chao,chan,chai,ceng,cang,bing,biao,bian,beng,bang".split(
            ",",
          ),
        ],
        [
          3,
          "zuo,zun,zui,zou,zhu,zhi,zhe,zha,zen,zei,zao,zan,zai,yun,yue,you,yin,yao,yan,xun,xue,xiu,xin,xie,xia,wen,wei,wan,wai,tuo,tun,tui,tou,tie,tao,tan,tai,suo,sun,sui,sou,shu,shi,she,sha,sen,sei,sao,san,sai,ruo,run,rui,rua,rou,ren,rao,ran,qun,que,qiu,qin,qie,qia,pou,pin,pie,pen,pei,pao,pan,pai,nü,nuo,nou,niu,nin,nie,nen,nei,nao,nan,nai,mou,miu,min,mie,men,mei,mao,man,mai,lü,luo,lun,lou,liu,lin,lie,lia,lei,lao,lan,lai,kuo,kun,kui,kua,kou,ken,kei,kao,kan,kai,jun,jue,jiu,jin,jie,jia,huo,hun,hui,hua,hou,hen,hei,hao,han,hai,guo,gun,gui,gua,gou,gen,gei,gao,gan,gai,fou,fen,fei,fan,duo,dun,dui,dou,diu,die,dia,den,dei,dao,dan,dai,cuo,cun,cui,cou,chu,chi,che,cha,cen,cao,can,cai,bin,bie,ben,bei,bao,ban,bai,ang".split(
            ",",
          ),
        ],
        [
          2,
          "zu,zi,ze,za,yu,yo,yi,ye,ya,xu,xi,wu,wo,wa,tu,ti,te,ta,su,si,se,sa,ru,ri,re,qu,qi,pu,po,pi,pa,ou,nu,ni,ng,ne,na,mu,mo,mi,me,ma,lu,li,le,la,ku,ke,ka,ju,ji,hu,he,ha,gu,ge,ga,fu,fo,fa,er,en,ei,du,di,de,da,cu,ci,ce,ca,bu,bo,bi,ba,ao,an,ai".split(
            ",",
          ),
        ],
        [1, "o,n,m,e,a,r".split(",")],
      ],
      a = [];
    for (const [n, e] of i) a.push(...e);
    const e = (n) => {
        n = String(n).toLowerCase();
        for (const i of n) {
          if (g.includes(i)) return 1;
          if (s.includes(i)) return 2;
          if (t.includes(i)) return 3;
          if (h.includes(i)) return 4;
        }
        return 0;
      },
      u = [
        ["āáǎăà", "a"],
        ["ēéěè", "e"],
        ["ōóǒò", "o"],
        ["ūúǔùǖǘǚǜ", "u"],
        ["īíǐì", "i"],
      ],
      o = (n) => {
        n = String(n).toLowerCase();
        for (const [i, a] of u)
          for (const e of i) n = n.replace(new RegExp(e, "g"), a);
        return n;
      },
      g = "āēūǖīō",
      s = "áéúǘíó",
      t = "ǎăěǔǚǐǒ",
      h = "àèùǜìò";
    class c {
      constructor(n, i) {
        ((this.location = n), (this.length = i));
      }
      _slice(n) {
        return n.slice(this.location, this.location + this.length);
      }
    }
    const r = (n) => {
      const a = [],
        e = o(n).replace("v", " "),
        u = e.length;
      let g = 0;
      for (; g < u; ) {
        let n,
          o = new RegExp("^[0-9]");
        if (
          !e[g].toLowerCase() === e[g] ||
          " " === e[g] ||
          o.test(e[g]) ||
          "’" === e[g] ||
          ";" === e[g] ||
          "/" === e[g] ||
          "[" === e[g] ||
          "]" === e[g] ||
          "!" === e[g] ||
          "." === e[g]
        )
          g += 1;
        else {
          for (const [a, o] of i)
            if (((n = e.slice(g, g + a)), o.includes(n))) {
              const o = g + a;
              if (a > 1 && o < u && "aoeiu".includes(e[o])) {
                const u = n.slice(0, -1);
                if (i[7 - a][1].includes(u))
                  if ("iu".includes(e[o])) n = u;
                  else
                    for (const [a, g] of i) {
                      const i = e.slice(o - 1, o - 1 + a);
                      if (g.includes(i)) {
                        n = u;
                        break;
                      }
                    }
              }
              break;
            }
          void 0 !== n && (a.push(new c(g, n.length)), (g += n.length));
        }
      }
      return a;
    };
    return {
      colorized_HTML_string_from_string: (i, a = "pinYinWrapper", u = n) => {
        i = String(i);
        const o = r(i);
        if (!o.length) return null;
        ((a = String(a)),
          (u = [
            String(u[0]),
            String(u[1]),
            String(u[2]),
            String(u[3]),
            String(u[4]),
          ]));
        const g = o.map((n) => n._slice(i)),
          s = g.map(e);
        if (!s.some((n) => 0 !== n))
          return `<span class="${a}"><span class="${u[0]}">${i}</span></span>`;
        let t = 0,
          h = `<span class="${a}">`;
        for (let n = 0; n < o.length; n++) {
          const a = o[n],
            e = g[n],
            c = s[n];
          ((h += i.slice(t, a.location)),
            (h += `<span class="${u[c]}">${e}</span>`),
            (t = a.location + a.length));
        }
        return (h += i.slice(t) + "</span>");
      },
      lowercase_string_by_removing_pinyin_tones: o,
    };
  }
  "undefined" != typeof module &&
    (module.exports = { pinyinWrapper: pinyinWrapper });
